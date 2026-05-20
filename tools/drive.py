"""
tools/drive.py — Google Drive API tools
Proyecto: llyc-ai-first-core
Owner: Max + Alberto
Sprint: 1

Alimenta:
  - Todos los agentes Sprint 1 → escritura de outputs en
    04_OUTPUTS/{cliente}/ (paso 8 del flujo end-to-end).
  - Sprint 1.5+ → lectura de ficheros editados por Jesús (loop de
    calificación) y de fichero append-only de acciones tomadas
    (weekly-digest, DEC_035). Esqueleto comentado al final.

Decisiones aplicadas:
  - DEC_022: contrato ok/error + timeout (drive 20s en TIMEOUTS)

Auth:
  La Cloud Function se ejecuta como SA
  llyc-agents-sa@llyc-ai-first-core.iam.gserviceaccount.com.
  google.auth.default() devuelve esas credenciales en runtime.
  Scope OAuth: https://www.googleapis.com/auth/drive (full).
  El control de qué ficheros toca se ejerce vía sharing granular
  (Drive UI), NO vía scope OAuth. Compartir cada carpeta nueva con
  la SA explícitamente.

Carpetas con acceso compartido a la SA (V&V Sprint 1):
  - 04_OUTPUTS/vidal-vidal/ → Editor
    (folder_id en config.drive.outputs_folder_id)
"""

import io
import json
import logging

import google.auth
from google.auth.exceptions import DefaultCredentialsError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from tools.response import ok, error, with_timeout

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
JSON_MIME_TYPE = "application/json"


# ─────────────────────────────────────────────
# INICIALIZACIÓN
# ─────────────────────────────────────────────

def init_drive_client():
    """
    Inicializa el cliente de Drive API v3 usando las credenciales por defecto
    del entorno (en Cloud Functions Gen 2 = la SA enlazada al servicio).

    En local requiere `gcloud auth application-default login` o variable
    GOOGLE_APPLICATION_CREDENTIALS apuntando a una key json.
    """
    try:
        credentials, _project = google.auth.default(scopes=DRIVE_SCOPES)
    except DefaultCredentialsError as e:
        raise RuntimeError(
            "No se pueden cargar las credenciales por defecto. "
            "En local: 'gcloud auth application-default login'. "
            f"En Cloud Functions debería usar la SA enlazada. Error: {e}"
        )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


# ─────────────────────────────────────────────
# HELPERS INTERNOS
# ─────────────────────────────────────────────

def _find_file_by_name_in_folder(service, folder_id: str, filename: str):
    """
    Busca un fichero por nombre exacto dentro de una carpeta.
    Devuelve el file_id si existe, None si no.
    Si hay múltiples ficheros con el mismo nombre (Drive lo permite),
    devuelve el primero.
    """
    safe_name = filename.replace("'", "\\'")
    query = (
        f"name = '{safe_name}' "
        f"and '{folder_id}' in parents "
        f"and trashed = false"
    )
    try:
        response = service.files().list(
            q=query,
            spaces="drive",
            fields="files(id, name)",
            pageSize=1,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
    except HttpError as e:
        log.warning(json.dumps({
            "event": "drive_find_file_error",
            "folder_id": folder_id,
            "filename": filename,
            "error": str(e),
        }))
        return None

    files = response.get("files", [])
    return files[0]["id"] if files else None


# ─────────────────────────────────────────────
# FUNCIONES PÚBLICAS — ESCRITURA
# ─────────────────────────────────────────────

@with_timeout("drive")
def write_output_to_drive(
    folder_id: str,
    filename: str,
    payload: dict,
    overwrite_if_exists: bool = True,
) -> dict:
    """
    Escribe un payload JSON como fichero en una carpeta de Drive.

    Args:
        folder_id: ID de la carpeta destino
            (config.drive.outputs_folder_id).
        filename: nombre con extensión (ej:
            '2026-05-20_PAID_performance-monitor-vidal-vidal.json').
        payload: dict serializable a JSON.
        overwrite_if_exists: si True (default), actualiza el contenido
            del fichero existente con mismo nombre. Si False, crea uno
            nuevo (Drive permite duplicados).

    Returns:
        ok dict con file_id, url y action ('created' o 'updated'),
        o error dict si falla.
    """
    service = init_drive_client()

    try:
        content = json.dumps(payload, indent=2, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        return error(
            "drive",
            "JSON_SERIALIZATION_ERROR",
            f"El payload no es serializable a JSON: {e}",
        )

    media = MediaIoBaseUpload(
        io.BytesIO(content.encode("utf-8")),
        mimetype=JSON_MIME_TYPE,
        resumable=False,
    )

    existing_id = None
    if overwrite_if_exists:
        existing_id = _find_file_by_name_in_folder(service, folder_id, filename)

    try:
        if existing_id:
            result = service.files().update(
                fileId=existing_id,
                media_body=media,
                fields="id, webViewLink",
                supportsAllDrives=True,
            ).execute()
            action = "updated"
        else:
            metadata = {
                "name": filename,
                "parents": [folder_id],
                "mimeType": JSON_MIME_TYPE,
            }
            result = service.files().create(
                body=metadata,
                media_body=media,
                fields="id, webViewLink",
                supportsAllDrives=True,
            ).execute()
            action = "created"

        log.info(json.dumps({
            "event": "drive_output_written",
            "folder_id": folder_id,
            "filename": filename,
            "file_id": result["id"],
            "action": action,
        }))

        return ok("drive", {
            "file_id": result["id"],
            "url": result.get("webViewLink"),
            "action": action,
            "filename": filename,
        })

    except HttpError as e:
        status = e.resp.status if hasattr(e, "resp") else None
        log.error(json.dumps({
            "event": "drive_write_http_error",
            "folder_id": folder_id,
            "filename": filename,
            "status_code": status,
            "error": str(e),
        }))
        return error(
            "drive",
            f"HTTP_{status or 'UNKNOWN'}",
            f"Error de Drive API al escribir '{filename}': {e}",
        )
    except Exception as e:
        log.error(json.dumps({
            "event": "drive_write_unexpected_error",
            "folder_id": folder_id,
            "filename": filename,
            "error": str(e),
        }))
        return error(
            "drive",
            "UNEXPECTED",
            f"Error inesperado al escribir '{filename}': {e}",
        )


# ─────────────────────────────────────────────
# FUNCIONES PÚBLICAS — LECTURA (Sprint 1.5)
# ─────────────────────────────────────────────

# Esqueleto pendiente — activar cuando:
#   1) El loop de calificación necesite leer el fichero editado por
#      Jesús con las calificaciones (✅⚠❌).
#   2) El weekly-digest necesite leer el fichero append-only de
#      acciones tomadas la semana anterior (DEC_035).
#
# @with_timeout("drive")
# def read_file_from_drive(file_id: str) -> dict:
#     """
#     Lee el contenido de un fichero de Drive por su ID.
#
#     Args:
#         file_id: ID del fichero a leer.
#
#     Returns:
#         ok dict con content (str), mime_type, name.
#         error dict si falla.
#     """
#     raise NotImplementedError("Pendiente de implementar en Sprint 1.5")
