"""
scripts/setup_agent.py — Onboarding de un agente para un cliente concreto.

Reemplaza a scripts/bootstrap_agent.py tras DEC_066 (descarte de Anthropic
Managed Agents). Antes el script creaba un agent server-side en Anthropic y
persistía agent_id; ahora el runtime usa Messages API + tool_use loop manual,
y el setup se reduce a depositar la API key del par (cliente, agente) en
Secret Manager, otorgar accessor a la SA del runtime, y marcar enabled=true
en el config.

Uso:
    python scripts/setup_agent.py --client vidal-vidal --agent performance_monitor

Opciones:
    --dry-run    Valida config + muestra preview del system prompt construido
                 + lista los pasos planificados. No toca Secret Manager ni config.

Flujo:
    1. Validar argumentos
    2. Cargar clients/<client>/config.json y validar campos críticos
    3. Construir preview del system prompt (estático + dinámico) reutilizando
       load_static_prompt() y build_dynamic_context() de main.py (DEC_066,
       sin duplicar la lógica entre script y runtime)
    4. (--dry-run) Imprimir preview + lista de pasos. Salir.
    5. (--no-dry-run) Solicitar API key con getpass (no flag, no shell history)
    6. Crear secret anthropic-api-key-<agent>-<client_id> en llyc-ai-<client_id>
       (o añadir nueva versión si ya existe)
    7. Asignar roles/secretmanager.secretAccessor a llyc-agents-sa@core
       sobre el secret (idempotente vía gcloud add-iam-policy-binding)
    8. Actualizar clients/<client>/config.json:
       config.agents[<agent_name>] = {enabled: true, created_at: <UTC>}
       (preserva agent_id histórico si existe — DEC_066)
    9. Imprimir comando curl listo para validación E2E

Decisiones aplicadas:
    - DEC_058 (act. 22/05): naming anthropic-api-key-<agent>-<client_id>
      en Secret Manager del proyecto cliente (llyc-ai-<client_id>)
    - DEC_059: filtro de plataformas en build_dynamic_context (delegado a main.py)
    - DEC_060-063: schema config v3.0
    - DEC_066: descarte de Managed Agents — sin agent creation server-side
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Permite ejecutar desde la raíz del repo: `python scripts/setup_agent.py ...`
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from google.cloud import secretmanager  # noqa: E402

from operational_inputs import (  # noqa: E402
    load_operational_inputs,
    reference_used,
    to_prompt_block,
)
from prompt_builder import load_static_prompt, build_dynamic_context  # noqa: E402
from tools.definitions import get_tool_definitions  # noqa: E402


# ─── CONSTANTES ──────────────────────────────────────────────────────────────

CORE_PROJECT_ID = "llyc-ai-first-core"
AGENTS_SA = "llyc-agents-sa@llyc-ai-first-core.iam.gserviceaccount.com"

SUPPORTED_AGENTS = {"performance_monitor", "naming_utm_auditor"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("setup_agent")


# ─── HELPERS ─────────────────────────────────────────────────────────────────


def load_config(client_id: str) -> tuple[Path, dict]:
    """Carga config.json del cliente y devuelve (path, dict)."""
    path = REPO_ROOT / "clients" / client_id / "config.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Config no encontrado: {path}. "
            f"¿Existe clients/{client_id}/config.json en el repo?"
        )
    with path.open("r", encoding="utf-8") as f:
        return path, json.load(f)


def validate_config(config: dict, agent_name: str) -> None:
    """
    Falla ruidosamente si campos críticos faltan o tienen valores no usables.

    Schema v3.0 (DEC_060-063). Diferencia respecto a bootstrap_agent.py:
    no exige enabled=true en agents.<agent_name> — ese campo lo setea ESTE
    script. Solo verifica los campos escalares críticos del config.
    """
    INVALID_SCALARS = {"PENDIENTE", "", None}

    scalar_required = [
        ("client.id", config.get("client", {}).get("id")),
        ("client.name", config.get("client", {}).get("name")),
        (
            "gcp.secret_manager_project",
            config.get("gcp", {}).get("secret_manager_project"),
        ),
    ]
    errors = [field for field, val in scalar_required if val in INVALID_SCALARS]

    if errors:
        raise ValueError(
            f"Config incompleto para agent '{agent_name}' en cliente "
            f"'{config.get('client', {}).get('id')}'. "
            f"Campos faltantes o vacíos: {errors}"
        )


def deposit_anthropic_api_key(
    client_project_id: str,
    secret_name: str,
    api_key_value: str,
) -> str:
    """
    Crea el secret en Secret Manager del proyecto cliente, o añade nueva
    versión si ya existe. Devuelve el resource name de la versión añadida.

    Labels: platform=anthropic, scope=client, client=<client_id>
    """
    sm_client = secretmanager.SecretManagerServiceClient()
    parent = f"projects/{client_project_id}"
    full_secret_name = f"{parent}/secrets/{secret_name}"
    client_id = client_project_id.replace("llyc-ai-", "")

    try:
        sm_client.get_secret(request={"name": full_secret_name})
        log.info(f"Secret existente: {secret_name}. Añadiendo nueva versión.")
    except Exception:
        log.info(f"Creando nuevo secret: {secret_name}")
        sm_client.create_secret(
            request={
                "parent": parent,
                "secret_id": secret_name,
                "secret": {
                    "replication": {"automatic": {}},
                    "labels": {
                        "platform": "anthropic",
                        "scope": "client",
                        "client": client_id,
                    },
                },
            }
        )

    version = sm_client.add_secret_version(
        request={
            "parent": full_secret_name,
            "payload": {"data": api_key_value.encode("utf-8")},
        }
    )
    log.info(f"Versión añadida: {version.name}")
    return version.name


def grant_secretmanager_accessor_to_agents_sa(
    client_project_id: str,
    secret_name: str,
) -> None:
    """
    Asigna roles/secretmanager.secretAccessor a la SA del runtime
    (llyc-agents-sa@llyc-ai-first-core) sobre el secret. Idempotente:
    add-iam-policy-binding no falla si el binding ya existe.
    """
    member = f"serviceAccount:{AGENTS_SA}"
    role = "roles/secretmanager.secretAccessor"

    cmd = [
        "gcloud",
        "secrets",
        "add-iam-policy-binding",
        secret_name,
        f"--member={member}",
        f"--role={role}",
        f"--project={client_project_id}",
        "--quiet",
    ]
    log.info(f"Grant IAM: {member} → {role} sobre {secret_name}")
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def update_config_agents_enabled(
    config_path: Path,
    config: dict,
    agent_name: str,
) -> None:
    """
    Marca enabled=true + created_at en config.agents[<agent_name>].
    Preserva agent_id si existe (trazabilidad histórica — DEC_066).
    Idempotente: si enabled ya es true, solo añade created_at si falta.
    """
    if "agents" not in config:
        config["agents"] = {}
    agent_block = config["agents"].setdefault(agent_name, {})

    was_enabled = agent_block.get("enabled", False)
    agent_block["enabled"] = True
    if "created_at" not in agent_block:
        agent_block["created_at"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )

    with config_path.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")

    if was_enabled:
        log.info(f"Config: agents[{agent_name}].enabled ya era true (no-op)")
    else:
        log.info(
            f"Config: agents[{agent_name}].enabled=true, "
            f"created_at={agent_block['created_at']}"
        )


def print_validation_curl(client_id: str, agent_name: str) -> None:
    """Imprime el comando curl listo para validar E2E el nuevo agente."""
    payload = json.dumps(
        {
            "client_id": client_id,
            "agent_name": agent_name.replace("_", "-"),
        }
    )
    print("\n" + "=" * 70)
    print("VALIDACIÓN E2E — pega y ejecuta:")
    print("=" * 70)
    print(
        f"""
curl -X POST https://europe-west1-llyc-ai-first-core.cloudfunctions.net/agent-executor \\
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \\
  -H "Content-Type: application/json" \\
  -d '{payload}' \\
  --max-time 360 \\
  -w "\\nHTTP %{{http_code}} | latency %{{time_total}}s\\n"
"""
    )
    print("=" * 70)


# ─── FLUJO PRINCIPAL ─────────────────────────────────────────────────────────


def setup(client_id: str, agent_name: str, dry_run: bool) -> None:
    log.info(f"Setup: client={client_id} agent={agent_name} dry_run={dry_run}")

    config_path, config = load_config(client_id)
    validate_config(config, agent_name)
    log.info(f"Config validado: {config_path}")

    static_prompt = load_static_prompt(agent_name)
    dynamic_context = build_dynamic_context(config, agent_name)

    # Espejo de main.py (DEC_075): el prompt real incluye el bloque de parámetros
    # operativos del workbook — el dry-run debe ejercitar el mismo path para que
    # el gate sea real (resolución naming/UTM incluida). Requiere ADC con scope
    # spreadsheets.readonly; sin él, load_operational_inputs degrada a fallback
    # y lo señala en el trace.
    enabled_platforms = [
        k
        for k, v in config.get("platforms", {}).items()
        if isinstance(v, dict) and v.get("enabled")
    ]
    oi = load_operational_inputs(config, agent_name, platforms=enabled_platforms)
    full_prompt = f"{static_prompt}\n\n{dynamic_context}\n\n{to_prompt_block(oi)}"
    log.info(f"System prompt construido: {len(full_prompt)} chars")
    log.info(
        f"Operational inputs: {json.dumps(reference_used(oi), ensure_ascii=False)}"
    )

    tools = get_tool_definitions(agent_name)
    log.info(
        f"Tools del catálogo del agente: {len(tools)} — {[t['name'] for t in tools]}"
    )

    if dry_run:
        print("\n" + "=" * 70)
        print("DRY RUN — no se toca Secret Manager ni config.json")
        print("=" * 70)
        print("\nSYSTEM PROMPT (preview, primeros 3000 chars):")
        print("-" * 70)
        print(full_prompt[:3000])
        if len(full_prompt) > 3000:
            print(f"\n... [truncado, total {len(full_prompt)} chars]")
        print("-" * 70)
        print("\nBLOQUE PARÁMETROS OPERATIVOS (completo, DEC_075):")
        print("-" * 70)
        print(to_prompt_block(oi))
        print("-" * 70)
        print("\nreference_used (gate 3.2):")
        print(json.dumps(reference_used(oi), indent=2, ensure_ascii=False))
        print("-" * 70)
        print("\nPASOS QUE EJECUTARÍA SIN --dry-run:")
        client_project_id = config["gcp"]["secret_manager_project"]
        secret_name = f"anthropic-api-key-{agent_name}-{client_id}"
        print("  1. Solicitar Anthropic API key (getpass, sin shell history)")
        print(f"  2. Crear/actualizar secret '{secret_name}' en {client_project_id}")
        print(f"  3. Grant 'roles/secretmanager.secretAccessor' a {AGENTS_SA}")
        print(f"  4. Marcar config.agents[{agent_name}].enabled=true + created_at")
        print("  5. Imprimir comando curl de validación E2E")
        print("=" * 70)
        return

    print()
    api_key = getpass.getpass(
        f"Anthropic API key para {agent_name}+{client_id} (no se mostrará): "
    ).strip()
    if not api_key:
        raise ValueError("API key vacía — abortando.")
    if not api_key.startswith("sk-ant-"):
        log.warning(
            "API key no tiene prefijo 'sk-ant-' esperado. "
            "Continuando, pero verifica manualmente que es válida."
        )

    client_project_id = config["gcp"]["secret_manager_project"]
    secret_name = f"anthropic-api-key-{agent_name}-{client_id}"
    deposit_anthropic_api_key(client_project_id, secret_name, api_key)

    grant_secretmanager_accessor_to_agents_sa(client_project_id, secret_name)

    update_config_agents_enabled(config_path, config, agent_name)

    print_validation_curl(client_id, agent_name)


# ─── CLI ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Onboarding de un agente para un cliente concreto (post-DEC_066). "
            "Reemplaza scripts/bootstrap_agent.py — Anthropic Managed Agents "
            "descartado; el runtime usa Messages API + tool_use loop manual. "
            "Este script deposita la API key del par (cliente, agente) en "
            "Secret Manager, otorga accessor a la SA del runtime, y marca "
            "enabled=true en el config."
        ),
    )
    parser.add_argument(
        "--client",
        required=True,
        help="ID del cliente (ej: vidal-vidal). Debe existir clients/<client>/config.json.",
    )
    parser.add_argument(
        "--agent",
        required=True,
        choices=sorted(SUPPORTED_AGENTS),
        help="Nombre del agente en snake_case (ej: performance_monitor).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Valida config y muestra preview del system prompt + pasos planificados. "
            "No toca Secret Manager ni config.json."
        ),
    )

    args = parser.parse_args()

    try:
        setup(
            client_id=args.client,
            agent_name=args.agent,
            dry_run=args.dry_run,
        )
    except Exception as e:
        log.error(f"Setup falló: {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
