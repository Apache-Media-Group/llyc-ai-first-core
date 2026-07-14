import base64
import logging

logger = logging.getLogger(__name__)

class EncryptionUtil:
    """
    Placeholder for EncryptionUtil. 
    In a production environment, this should use Google Cloud KMS or a library like Tink.
    For this standalone prototype, we use a simple Base64 encoding as a placeholder.
    """
    def __init__(self, project_id: str = None):
        self.project_id = project_id
        logger.warning("Using placeholder EncryptionUtil. DO NOT USE IN PRODUCTION.")

    def encrypt(self, data: str) -> str:
        if not data:
            return ""
        return base64.b64encode(data.encode()).decode()

    def decrypt(self, encrypted_data: str) -> str:
        if not encrypted_data:
            return ""
        try:
            return base64.b64decode(encrypted_data.encode()).decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            return encrypted_data # Fallback to original if not actually encrypted
