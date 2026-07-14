import os
import logging
from typing import Dict, List, Optional, Any, Tuple
import requests
from fastapi import Request
from app.core.config import settings
import google.cloud.firestore as firestore
from google.cloud.firestore import Client, Query
from datetime import datetime
from .encryption_utils import EncryptionUtil

logger = logging.getLogger(__name__)

# --- 2026-03-09: Shared Auth Utilities ---

def get_effective_redirect_uri(request: Request, provided_redirect_uri: Optional[str] = None) -> str:
    """Determines the correct redirect URI based on settings or request origin."""
    if provided_redirect_uri:
        return provided_redirect_uri
        
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    
    # Standardize local development to port 3000 for Platform Login
    if host and ("localhost" in host or "127.0.0.1" in host):
        return "http://localhost:3000/auth/callback"

    if settings.GOOGLE_REDIRECT_URI:
        return settings.GOOGLE_REDIRECT_URI
        
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    if host and (".a.run.app" in host or ".app" in host or "run.app" in host):
        proto = "https"
    
    return f"{proto}://{host}/auth/callback"

def get_backend_callback_url(request: Request, path: str = "/api/v1/mcp-analytics/oauth/callback") -> str:
    """Generates a callback URL that points directly to the backend."""
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    
    if host and ("localhost" in host or "127.0.0.1" in host):
        return f"http://localhost:8000{path}"

    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    if host and (".a.run.app" in host or ".app" in host or "run.app" in host):
        proto = "https"
    
    return f"{proto}://{host}{path}"

class RBACManager:
    """Manages Role-Based Access Control for connections."""
    
    ROLES = {
        "ADMIN": "admin",
        "VIEWER": "viewer"
    }

    @staticmethod
    def can_edit(permissions: Dict[str, str], user_email: str) -> bool:
        """Checks if a user has admin permissions."""
        if not user_email or not permissions: return False
        try:
            # Normalize to lowercase and strip for matching
            normalized_permissions = {str(k).lower().strip(): str(v).lower().strip() for k, v in permissions.items()}
            return normalized_permissions.get(user_email.lower().strip()) == RBACManager.ROLES["ADMIN"]
        except Exception as e:
            logger.error(f"Error in RBACManager.can_edit: {e}")
            return False

    @staticmethod
    def can_view(permissions: Dict[str, str], user_email: str) -> bool:
        """Checks if a user has at least viewer permissions."""
        if not user_email or not permissions: return False
        try:
            # Normalize to lowercase and strip for matching
            u_email_low = user_email.lower().strip()
            normalized_permissions = {str(k).lower().strip(): str(v).lower().strip() for k, v in permissions.items()}
            role = normalized_permissions.get(u_email_low)
            is_valid = role in [RBACManager.ROLES["ADMIN"], RBACManager.ROLES["VIEWER"]]
            
            if not is_valid:
                logger.debug(f"RBAC: User '{u_email_low}' not found in permissions keys: {list(normalized_permissions.keys())}")
            
            return is_valid
        except Exception as e:
            logger.error(f"Error in RBACManager.can_view: {e}")
            return False

class TokenManager:
    """Manages connection tokens and metadata in Firestore."""
    
    SENSITIVE_TOKEN_KEYS = [
        "client_secret", "access_token", "refresh_token", "ADOBE_CLIENT_SECRET",
        "GOOGLE_ADS_DEVELOPER_TOKEN", "client_id", "private_key", "client_email",
        "app_id", "app_secret", "secret", "org_id"
    ]

    def __init__(self, project_id: Optional[str] = None):
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID") or settings.GCP_PROJECT_ID
        self._db = None
        self.collection = "connections"
        self.enc_util = EncryptionUtil(self.project_id)

    @property
    def db(self):
        if self._db is None:
            try:
                self._db = Client(project=self.project_id)
                logger.info(f"Firestore Client initialized for project: {self.project_id}")
            except Exception as e:
                logger.error(f"ERROR: Failed to initialize Firestore Client: {e}")
        return self._db

    def _encrypt_tokens(self, tokens: Dict[str, Any]) -> Dict[str, Any]:
        """Encrypts sensitive tokens."""
        encrypted_tokens = tokens.copy()
        for key in self.SENSITIVE_TOKEN_KEYS:
            if key in encrypted_tokens and isinstance(encrypted_tokens[key], str):
                encrypted_tokens[key] = self.enc_util.encrypt(encrypted_tokens[key])
        return encrypted_tokens

    def _decrypt_tokens(self, tokens: Dict[str, Any]) -> Dict[str, Any]:
        """Decrypts sensitive tokens."""
        decrypted_tokens = tokens.copy()
        logger.debug(f"Attempting to decrypt tokens with keys: {list(tokens.keys())}")
        for key in self.SENSITIVE_TOKEN_KEYS:
            if key in decrypted_tokens and isinstance(decrypted_tokens[key], str):
                val = decrypted_tokens[key]
                if val.startswith("gAAAA"): # Fernet standard prefix
                    try:
                        decrypted_tokens[key] = self.enc_util.decrypt(val)
                        logger.debug(f"Decrypted key: {key}")
                    except Exception as e:
                        logger.error(f"Decryption failed for key {key}: {e}")
                else:
                    logger.debug(f"Key {key} does not appear to be encrypted (skipping). Prefix: {val[:5]}...")
        return decrypted_tokens

    def save_connection(
        self, 
        connection_id: str, 
        platform: str, 
        tokens: Dict[str, Any], 
        admin_email: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Saves or updates a connection with initial admin."""
        if not self.db: return
        
        doc_ref = self.db.collection(self.collection).document(connection_id)
        encrypted_tokens = self._encrypt_tokens(tokens)
        
        # Normalize email to lowercase and strip for consistent RBAC
        admin_email_low = admin_email.lower().strip()

        data = {
            "platform": platform,
            "tokens": encrypted_tokens,
            "permissions": {admin_email_low: RBACManager.ROLES["ADMIN"]},
            "metadata": metadata or {},
            "updated_at": firestore.SERVER_TIMESTAMP
        }
        
        doc = doc_ref.get()
        if not doc.exists:
            data["created_at"] = firestore.SERVER_TIMESTAMP
        else:
            existing_data = doc.to_dict()
            existing_permissions = existing_data.get("permissions") or {}
            # Merge permissions
            if admin_email_low not in existing_permissions:
                existing_permissions[admin_email_low] = RBACManager.ROLES["ADMIN"]
            data["permissions"] = existing_permissions
            
            # Merge metadata
            existing_metadata = existing_data.get("metadata") or {}
            if metadata:
                existing_metadata.update(metadata)
            data["metadata"] = existing_metadata

        doc_ref.set(data, merge=True)
        logger.info(f"Connection {connection_id} saved/merged for admin {admin_email_low}")

    def get_connection(self, connection_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves connection data."""
        if not self.db: return None
        doc = self.db.collection(self.collection).document(connection_id).get()
        if doc.exists:
            data = doc.to_dict()
            if "tokens" in data:
                data["tokens"] = self._decrypt_tokens(data["tokens"])
            return data
        return None

    def list_user_connections(self, user_email: str) -> List[Dict[str, Any]]:
        """Lists all connections where the user has at least viewer access."""
        if not self.db: return []
        
        target_email = user_email.lower().strip()
        logger.info(f"RBAC: Listing connections for user: '{target_email}'")
        try:
            docs = self.db.collection(self.collection).stream()
            user_connections = []
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                
                permissions = data.get("permissions")
                if not isinstance(permissions, dict):
                    logger.warning(f"RBAC: Connection {doc.id} has invalid permissions format: {type(permissions)}")
                    permissions = {}
                
                if RBACManager.can_view(permissions, target_email):
                    logger.debug(f"RBAC: User '{target_email}' ALLOWED for connection {doc.id}")
                    if "tokens" in data:
                        data["tokens"] = self._decrypt_tokens(data["tokens"])
                    user_connections.append(data)
                else:
                    # Log rejection at debug level to avoid spam but allow tracing
                    logger.debug(f"RBAC: User '{target_email}' REJECTED for connection {doc.id}. Perms: {permissions}")
            
            logger.info(f"RBAC: Found {len(user_connections)} connections for '{target_email}'")
            return user_connections
        except Exception as e:
            logger.error(f"Error in list_user_connections: {e}")
            return []

    def update_permissions(self, connection_id: str, user_email: str, role: str, admin_email: str):
        """Updates permissions for a user. Must be called by an admin."""
        if not self.db: return
        
        doc_ref = self.db.collection(self.collection).document(connection_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            raise Exception("Connection not found")
            
        data = doc.to_dict()
        permissions = data.get("permissions") or {}
        
        # Normalize admin email for check
        if not RBACManager.can_edit(permissions, admin_email.lower().strip()):
            raise Exception("Unauthorized: Only admins can manage permissions")
            
        user_email_low = user_email.lower().strip()
        if role is None: 
            if user_email_low in permissions:
                del permissions[user_email_low]
        else:
            permissions[user_email_low] = role.lower().strip()
            
        doc_ref.set({"permissions": permissions, "updated_at": firestore.SERVER_TIMESTAMP}, merge=True)
        logger.info(f"RBAC: Updated permissions for {connection_id}: {user_email_low} = {role}")

    def delete_connection(self, connection_id: str, admin_email: str):
        """Deletes a connection. Must be called by an admin."""
        if not self.db: return
        
        doc_ref = self.db.collection(self.collection).document(connection_id)
        doc = doc_ref.get()
        
        if not doc.exists: return
            
        data = doc.to_dict()
        if not RBACManager.can_edit(data.get("permissions", {}), admin_email):
            raise Exception("Unauthorized: Only admins can delete connections")
            
        doc_ref.delete()

class OAuthStateManager:
    """Manages short-lived OAuth states in Firestore with encryption."""
    
    def __init__(self, project_id: Optional[str] = None):
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID")
        self._db = None
        self.collection = "oauth_states"
        self.enc_util = EncryptionUtil(self.project_id)

    @property
    def db(self):
        if self._db is None:
            try:
                self._db = Client(project=self.project_id)
            except Exception as e:
                logger.error(f"ERROR: Failed to initialize Firestore Client in OAuthStateManager: {e}")
        return self._db

    def save_state(self, state: str, data: Dict[str, Any], ttl_seconds: int = 600):
        """Saves state data to Firestore, encrypting code_verifier if present."""
        if not self.db: return

        encrypted_data = data.copy()
        if "code_verifier" in encrypted_data:
            encrypted_data["code_verifier"] = self.enc_util.encrypt(encrypted_data["code_verifier"])
            
        doc_ref = self.db.collection(self.collection).document(state)
        doc_ref.set({
            "data": encrypted_data,
            "created_at": firestore.SERVER_TIMESTAMP,
            "expires_at": datetime.utcnow().timestamp() + ttl_seconds
        })

    def get_state(self, state: str) -> Optional[Dict[str, Any]]:
        """Retrieves and decrypts state data."""
        if not self.db: return None
            
        doc_ref = self.db.collection(self.collection).document(state)
        doc = doc_ref.get()
        
        if not doc.exists: return None
            
        data_doc = doc.to_dict()
        if data_doc.get("expires_at", 0) < datetime.utcnow().timestamp():
            doc_ref.delete()
            return None
            
        data = data_doc.get("data", {})
        if "code_verifier" in data:
            data["code_verifier"] = self.enc_util.decrypt(data["code_verifier"])
                
        return data

    def delete_state(self, state: str):
        """Deletes a state after use."""
        if not self.db: return
        self.db.collection(self.collection).document(state).delete()

class GoogleOAuth2Helper:
    """Helper for Google OAuth2 flow."""
    
    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    
    @staticmethod
    def generate_pkce() -> Tuple[str, str]:
        """Generates a code_verifier and code_challenge for PKCE."""
        import hashlib
        import base64
        import secrets
        
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode('ascii')).digest()
        ).decode('ascii').replace('=', '')
        
        return code_verifier, code_challenge

    @staticmethod
    def get_auth_url(client_id: str, redirect_uri: str, scopes: List[str], state: str, code_challenge: Optional[str] = None) -> str:
        """Generates the Google Authorization URL."""
        import urllib.parse
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
            "access_type": "offline",
            "prompt": "consent"
        }
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
            
        query_string = urllib.parse.urlencode(params)
        return f"{GoogleOAuth2Helper.AUTH_URL}?{query_string}"
    
    @staticmethod
    def get_tokens(client_id: str, client_secret: str, code: str, redirect_uri: str, code_verifier: Optional[str] = None) -> Dict[str, Any]:
        """Exchanges the authorization code for tokens."""
        data = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
            
        response = requests.post(GoogleOAuth2Helper.TOKEN_URL, data=data)
        if not response.ok:
            response.raise_for_status()
        return response.json()


# --- Adobe Analytics Specific Credential Management ---
ADOBE_ANALYTICS_PLATFORM = "adobe_analytics"

async def store_adobe_credentials(user_email: str, connection_id: str, credentials_data: Dict[str, Any]) -> None:
    token_manager = TokenManager()
    token_manager.save_connection(
        connection_id=connection_id,
        platform=ADOBE_ANALYTICS_PLATFORM,
        tokens=credentials_data,
        admin_email=user_email,
        metadata={"user_email": user_email}
    )
    
async def get_adobe_credentials(user_email: str, connection_id: Optional[str] = None) -> Any:
    token_manager = TokenManager()
    
    if connection_id:
        connection = token_manager.get_connection(connection_id)
        if connection and connection.get("platform") == ADOBE_ANALYTICS_PLATFORM:
            if RBACManager.can_view(connection.get("permissions", {}), user_email):
                return connection["tokens"]
        return None
    else:
        all_connections = token_manager.list_user_connections(user_email)
        adobe_connections = []
        for conn in all_connections:
            if conn.get("platform") == ADOBE_ANALYTICS_PLATFORM:
                adobe_connections.append({**conn["tokens"], "connection_id": conn["id"]})
        return adobe_connections

# --- General Auth Utilities for Cloud Functions ---
def validate_auth_token(token: str) -> bool:
    return bool(token)

def get_user_id(token: str = None) -> str:
    return os.getenv("DEFAULT_CLOUD_FUNCTION_USER_ID", "cloud_function_user@example.com")
