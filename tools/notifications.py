"""
tools/notifications.py — Notificaciones por email vía Gmail API
Proyecto: llyc-ai-first-core
Owner: Max + Alberto
Sprint: 1

Alimenta: agent_executor (paso 9 del flujo §9) → envía emails cuando
el output del agente tiene STATUS en config.notifications.alert_on_status.

Decisiones aplicadas:
  - DEC_022: contrato ok/error + timeout (gmail 30s en TIMEOUTS)

Auth:
  Gmail API con OAuth refresh_token. Los 3 secrets viven en
  llyc-ai-first-core (Secret Manager):
    - GMAIL_CLIENT_ID
    - GMAIL_CLIENT_SECRET
    - GMAIL_REFRESH_TOKEN
  El refresh_token fue generado autenticando admin-tech@llyc.global,
  por lo que los emails salen 'from: admin-tech@llyc.global'.

  Scope OAuth: gmail.send (mínimo privilegio — solo envío, no lectura).

Recipients y filtros se leen del config del cliente:
  - config.notifications.alert_recipients (lista de emails)
  - config.notifications.alert_on_status (lista de status que disparan)
"""

import base64
import json
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.cloud import secretmanager
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from tools.response import ok, error, with_timeout

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────

CORE_PROJECT_ID = "llyc-ai-first-core"
FROM_ADDRESS = "admin-tech@llyc.global"
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

SECRET_CLIENT_ID = "GMAIL_CLIENT_ID"
SECRET_CLIENT_SECRET = "GMAIL_CLIENT_SECRET"
SECRET_REFRESH_TOKEN = "GMAIL_REFRESH_TOKEN"


# ─────────────────────────────────────────────
# CARGA DE CREDENCIALES
# ─────────────────────────────────────────────

def _load_gmail_credentials() -> Credentials:
    """
    Lee los 3 secrets GMAIL_* de Secret Manager (proyecto core) y construye
    el objeto Credentials. El SDK refresca el access token automáticamente.

    Returns:
        Credentials válidas para enviar emails desde admin-tech@llyc.global.
    """
    sm_client = secretmanager.SecretManagerServiceClient()

    def _access(name: str) -> str:
        path = f"projects/{CORE_PROJECT_ID}/secrets/{name}/versions/latest"
        response = sm_client.access_secret_version(request={"name": path})
        return response.payload.data.decode("utf-8").strip()

    client_id = _access(SECRET_CLIENT_ID)
    client_secret = _access(SECRET_CLIENT_SECRET)
    refresh_token = _access(SECRET_REFRESH_TOKEN)

    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=GMAIL_SCOPES,
    )


# ─────────────────────────────────────────────
# INICIALIZACIÓN DEL CLIENTE
# ─────────────────────────────────────────────

def init_gmail_client():
    """
    Inicializa el cliente de Gmail API v1 con las credenciales OAuth.
    """
    credentials = _load_gmail_credentials()
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


# ─────────────────────────────────────────────
# HELPERS INTERNOS
# ─────────────────────────────────────────────

def _build_mime_message(
    recipients: list,
    subject: str,
    body_html: str,
    body_text: str,
) -> dict:
    """
    Construye un MIME multipart/alternative con html + plain text fallback
    y lo serializa a base64url tal como espera la Gmail API.
    """
    msg = MIMEMultipart("alternative")
    msg["From"] = FROM_ADDRESS
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject

    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return {"raw": raw}


# ─────────────────────────────────────────────
# FUNCIÓN PÚBLICA — ENVÍO DE EMAIL
# ─────────────────────────────────────────────

@with_timeout("gmail")
def send_alert_email(
    recipients: list,
    subject: str,
    body_html: str,
    body_text: str,
    drive_url: str = None,
) -> dict:
    """
    Envía un email de alerta vía Gmail API a una lista de recipients.

    Args:
        recipients: lista de emails destinatarios.
        subject: asunto del email.
        body_html: cuerpo en HTML.
        body_text: fallback plain text para clientes que no renderizan HTML.
        drive_url: opcional, URL del output en Drive (se logguea como referencia).

    Returns:
        ok dict con message_id y recipients, o error dict si falla.
    """
    if not recipients:
        return error("gmail", "NO_RECIPIENTS", "Lista de recipients vacía.")

    service = init_gmail_client()
    message_body = _build_mime_message(recipients, subject, body_html, body_text)

    try:
        result = service.users().messages().send(
            userId="me",
            body=message_body,
        ).execute()

        log.info(json.dumps({
            "event": "gmail_alert_sent",
            "recipients_count": len(recipients),
            "subject": subject,
            "message_id": result.get("id"),
            "drive_url": drive_url,
        }))

        return ok("gmail", {
            "message_id": result.get("id"),
            "thread_id": result.get("threadId"),
            "recipients": recipients,
            "subject": subject,
        })

    except HttpError as e:
        status = e.resp.status if hasattr(e, "resp") else None
        log.error(json.dumps({
            "event": "gmail_send_http_error",
            "recipients_count": len(recipients),
            "subject": subject,
            "status_code": status,
            "error": str(e),
        }))
        return error(
            "gmail",
            f"HTTP_{status or 'UNKNOWN'}",
            f"Error de Gmail API al enviar: {e}",
        )

    except Exception as e:
        log.error(json.dumps({
            "event": "gmail_send_unexpected_error",
            "recipients_count": len(recipients),
            "subject": subject,
            "error": str(e),
        }))
        return error(
            "gmail",
            "UNEXPECTED",
            f"Error inesperado al enviar email: {e}",
        )
