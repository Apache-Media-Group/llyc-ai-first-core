"""
scripts/bootstrap_agent.py — Crea Managed Agent en Anthropic + persiste agent_id.

Uso:
    python scripts/bootstrap_agent.py --client vidal-vidal --agent performance_monitor

Opciones útiles:
    --dry-run                     Construye y muestra el prompt sin llamar a Anthropic
    --force                       Sobrescribe un agent_id existente (no placeholder)
    --prompt-dir system_prompts   Override del directorio de prompts estáticos

Flujo:
    1. Carga clients/<client>/config.json
    2. Valida campos críticos del config
    3. Lee system_prompts/<agent>.md (parte estática)
    4. Inyecta contexto dinámico desde config (cliente, KPIs, plataformas, etc.)
    5. Carga tool_definitions desde tools/definitions.py (DEC_021)
    6. Lee ANTHROPIC_API_KEY desde Secret Manager (llyc-ai-first-core)
    7. Crea Managed Agent en Anthropic (beta managed-agents-2026-04-01)
    8. Persiste agent_id real en clients/<client>/config.json (reemplaza placeholder)
    9. Imprime resumen final

Idempotencia: si el agent_id ya no es un placeholder, aborta salvo `--force`.
Esto evita re-crear agents accidentalmente (cuesta tokens en Anthropic y
desincroniza config con la fuente de verdad server-side).

Decisiones aplicadas:
    - DEC_021: tool_definitions en tools/definitions.py (catálogo + dict por agente)
    - DEC_058: ANTHROPIC_API_KEY por agente+cliente en Secret Manager del proyecto cliente
      (llyc-ai-{client_id}), no en core — Actualización 2026-05-22 de DEC_058.
    - arquitectura-sistema §3: system prompt = static (file) + dynamic (config)

⚠️ KNOWN ISSUES — refactor pendiente vs config schema v3.0 (post-revisión Sara 24/05,
   DEC_060-063). Este script fue desarrollado el 22/05 contra el schema v2 anterior.
   Los siguientes campos del schema viejo NO existen en v3.0:
     - `kpis.roas_target` → ahora `kpis.roas_blended_base_target` (DEC_061)
     - `kpis.monthly_budget_eur` → ahora `presupuesto_2026.mensual.{YYYY-MM}.total`
     - `thresholds.*` → ahora `umbrales.*` con sub-estructura distinta
     - `agents.X.output_drive_folder` → ahora `output_folder` con path relativo
     - `agents.X.schedule_cron` → ahora `schedule` (sin sufijo _cron)
     - `notifications.alert_on_status` → ahora `alert_levels`
   Refactor de `validate_config()` y `build_dynamic_context()` necesario antes de
   ejecutar el primer bootstrap real contra V&V. Issue separada — no scope de este PR.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Permite ejecutar el script desde la raíz del repo: `python scripts/bootstrap_agent.py ...`
# sin necesidad de PYTHONPATH ni `-m`. Inserta la raíz del repo al principio del path.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from anthropic import Anthropic  # noqa: E402
from google.cloud import secretmanager  # noqa: E402

from tools.definitions import get_tool_definitions  # noqa: E402


# ─── CONSTANTES ──────────────────────────────────────────────────────────────

CORE_PROJECT_ID = "llyc-ai-first-core"

# Beta header pasado como parámetro `betas=[...]` a client.beta.agents.create()
# (verificado contra anthropic-0.103.1, mayo 2026 — help(c.beta.agents.create)).
ANTHROPIC_BETA = "managed-agents-2026-04-01"

# Modelo de referencia del proyecto (META_roles-herramientas-stack §3).
# Aceptado como string directo por la API; alternativamente se puede pasar un
# objeto model_config para control adicional.
DEFAULT_MODEL = "claude-sonnet-4-6"

# Agentes que este script sabe bootstrappear. Ampliar cuando se desarrollen
# los siguientes (budget_pacer, naming_utm_auditor, weekly_digest, ...).
SUPPORTED_AGENTS = {"performance_monitor"}

# Prefijos que indican que el agent_id en config sigue siendo el placeholder
# inicial. Si empieza por uno de estos, no se ha bootstrappeado todavía.
PLACEHOLDER_PREFIXES = (
    "perf-monitor-",
    "budget-pacer-",
    "naming-auditor-",
    "weekly-digest-",
    "creative-fatigue-",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("bootstrap_agent")


# ─── HELPERS ─────────────────────────────────────────────────────────────────


def get_secret(secret_name: str, project_id: str = CORE_PROJECT_ID) -> str:
    """Lee 'latest' de un secret de GCP Secret Manager. `.strip()` defensivo."""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(name=name)
    return response.payload.data.decode("UTF-8").strip()


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
    Mejor abortar aquí que enviar un prompt incompleto a Anthropic.
    """
    INVALID_SCALARS = {"PENDIENTE", "", None}

    # Campos escalares (string/número) — check contra valores inválidos conocidos
    scalar_required = [
        ("client.id",                      config.get("client", {}).get("id")),
        ("client.name",                    config.get("client", {}).get("name")),
        ("kpis.roas_target",               config.get("kpis", {}).get("roas_target")),
        ("kpis.monthly_budget_eur",        config.get("kpis", {}).get("monthly_budget_eur")),
        ("thresholds.roas_deviation_pct", config.get("thresholds", {}).get("roas_deviation_pct")),
    ]
    errors = [field for field, val in scalar_required if val in INVALID_SCALARS]

    # Bloque del agente — es un dict, requiere check separado (los dicts no son hashables)
    agent_block = config.get("agents", {}).get(agent_name)
    if not agent_block:
        errors.append(f"agents.{agent_name} (bloque ausente o vacío)")

    if errors:
        raise ValueError(
            f"Config incompleto para agent '{agent_name}' en cliente "
            f"'{config.get('client', {}).get('id')}'. Campos faltantes o vacíos: {errors}"
        )


def load_static_prompt(agent_name: str, prompt_dir: Path) -> str:
    """Lee el static system prompt desde system_prompts/<agent>.md."""
    path = prompt_dir / f"{agent_name}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"System prompt no encontrado: {path}. "
            f"El static prompt vive en el repo siguiendo el patrón "
            f"system_prompts/<agent>.md. Crear el fichero con el prompt "
            f"diseñado en Capa 1 (Drive: 02_ARQUITECTURA/system-prompts/)."
        )
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(
            f"System prompt vacío: {path}. "
            f"Pegar el contenido del prompt estático antes de bootstrappear."
        )
    return content


def build_dynamic_context(config: dict, agent_name: str) -> str:
    """
    Construye la sección 'CONTEXTO DEL CLIENTE' que se inyecta al final del
    static prompt. Es lo que cambia entre clientes — el static prompt queda
    fijo, el dinámico se reconstruye en cada bootstrap.
    """
    client = config["client"]
    kpis = config["kpis"]
    thresholds = config["thresholds"]
    platforms = config["platforms"]
    agent_cfg = config["agents"][agent_name]
    notifications = config.get("notifications", {})

    # Plataformas que entran al contexto deben cumplir DOS condiciones:
    #   1. enabled=true en el config del cliente
    #   2. Tener al menos una tool disponible en el catálogo del agente
    # Esto evita inyectar plataformas que el agente no puede consultar (ej. DV360 en
    # performance_monitor: enabled=true en el config pero no tiene tool en el catálogo —
    # DV360 vive en un MCP server externo separado, fuera del scope de este agente).
    tool_names_for_agent = {t["name"] for t in get_tool_definitions(agent_name)}
    KNOWN_PLATFORMS = ["meta", "google_ads", "ga4", "tiktok", "dv360", "shopify"]
    platforms_with_tools = {
        p for p in KNOWN_PLATFORMS
        if any(p in tn for tn in tool_names_for_agent)
    }
    active_platforms = {
        k: v for k, v in platforms.items()
        if v.get("enabled") and k in platforms_with_tools
    }
    platforms_json = json.dumps(active_platforms, indent=2, ensure_ascii=False)

    return f"""

# CONTEXTO DEL CLIENTE

Cliente: {client['name']} (id: {client['id']})
Sector: {client.get('sector', 'N/A')}
País/Idioma/Moneda: {client.get('country', 'ES')}/{client.get('language', 'es')}/{client.get('currency', 'EUR')}
Zona horaria: {client.get('timezone', 'Europe/Madrid')}

## KPIs
- ROAS objetivo: {kpis['roas_target']}
- Presupuesto mensual (EUR): {kpis['monthly_budget_eur']}
- Revenue objetivo (EUR): {kpis.get('revenue_target_eur', 'N/A')}
- CPA objetivo (EUR): {kpis.get('cpa_target_eur', 'N/A')}
- CTR benchmark (%): {kpis.get('ctr_benchmark_pct', 'N/A')}

## Umbrales de desviación
- ROAS (%): {thresholds['roas_deviation_pct']}
- CPA (%): {thresholds.get('cpa_deviation_pct', 'N/A')}
- Budget (%): {thresholds['budget_deviation_pct']}

## Plataformas activas e identificadores
```json
{platforms_json}
```

## Output
- Carpeta destino en Drive: {agent_cfg['output_drive_folder']}
- Schedule: {agent_cfg['schedule_cron']}

## Notificaciones
- Canal: {notifications.get('alert_channel', 'email')}
- Destinatarios: {notifications.get('alert_recipients', [])}
- Dispara en STATUS: {notifications.get('alert_on_status', ['ALERTA', 'ERROR'])}
""".rstrip()


def is_placeholder(agent_id: str) -> bool:
    """True si el agent_id sigue siendo el placeholder inicial del config."""
    return any(agent_id.startswith(p) for p in PLACEHOLDER_PREFIXES)


# ─── CREACIÓN DEL AGENT EN ANTHROPIC ─────────────────────────────────────────


def create_managed_agent(
    api_key: str,
    name: str,
    system_prompt: str,
    tools: list[dict],
    model: str = DEFAULT_MODEL,
    description: str | None = None,
) -> str:
    """
    Llama a la API beta managed-agents-2026-04-01 de Anthropic para crear
    el agent y devuelve el agent_id resultante.

    Firma verificada contra anthropic-0.103.1 (mayo 2026):
        client.beta.agents.create(*, model, name, system, tools, betas, ...)

    Notas operativas:
        - El system prompt admite hasta 100,000 chars
        - Tools: máximo 128
        - El agente es server-side: una vez creado, el `agent_id` se reutiliza
          en cada ejecución. Para iterar el prompt sin re-crear, usar
          client.beta.agents.update() o versions (no implementado aquí).
    """
    client = Anthropic(api_key=api_key)

    response = client.beta.agents.create(
        model=model,
        name=name,
        system=system_prompt,
        tools=tools,
        description=description,
        betas=[ANTHROPIC_BETA],
    )

    return response.id


# ─── FLUJO PRINCIPAL ─────────────────────────────────────────────────────────


def bootstrap(
    client_id: str,
    agent_name: str,
    prompt_dir: Path,
    force: bool,
    dry_run: bool,
) -> str:
    log.info(f"Bootstrap: client={client_id} agent={agent_name}")

    # 1-2. Config
    config_path, config = load_config(client_id)
    validate_config(config, agent_name)
    log.info(f"Config validado: {config_path}")

    # Idempotencia
    current_id = config["agents"][agent_name].get("agent_id", "")
    if not is_placeholder(current_id) and not force:
        log.error(
            f"Agent '{agent_name}' ya bootstrappeado con agent_id='{current_id}'. "
            f"Pasa --force para sobrescribir (re-crea el agent en Anthropic, "
            f"el anterior queda huérfano)."
        )
        sys.exit(2)

    # 3-4. System prompt completo
    static_prompt = load_static_prompt(agent_name, prompt_dir)
    dynamic_context = build_dynamic_context(config, agent_name)
    full_prompt = f"{static_prompt}\n\n{dynamic_context}"
    log.info(f"System prompt: {len(full_prompt)} chars")

    # 5. Tools
    tools = get_tool_definitions(agent_name)
    log.info(f"Tools: {len(tools)} — {[t['name'] for t in tools]}")

    if dry_run:
        log.info("DRY RUN — no se llama a Anthropic")
        print("\n" + "=" * 70)
        print("SYSTEM PROMPT (preview)")
        print("=" * 70)
        print(full_prompt[:3000])
        if len(full_prompt) > 3000:
            print(f"\n... [truncado, total {len(full_prompt)} chars]")
        print("=" * 70)
        return "DRY_RUN_NO_AGENT_ID"

    # 6. API key — DEC_058 Actualización 2026-05-22: vive en proyecto del cliente
    client_project_id = f"llyc-ai-{client_id}"
    secret_name = f"anthropic-api-key-{agent_name}-{client_id}"
    log.info(f"Leyendo API key: {secret_name} (proyecto {client_project_id})")
    api_key = get_secret(secret_name, client_project_id)

    # 7. Crear agent
    # Display name en kebab-case para legibilidad en la consola de Anthropic
    display_name = f"{agent_name}-{client_id}".replace("_", "-")
    description = (
        f"Agente {agent_name} para {config['client']['name']}. "
        f"Detecta y analiza — no toma decisiones."
    )
    log.info(f"Creando Managed Agent: {display_name}")
    agent_id = create_managed_agent(
        api_key=api_key,
        name=display_name,
        system_prompt=full_prompt,
        tools=tools,
        description=description,
    )
    log.info(f"Agent creado en Anthropic: {agent_id}")

    # 8. Persistir agent_id en config
    config["agents"][agent_name]["agent_id"] = agent_id
    with config_path.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")
    log.info(f"Config actualizado: {config_path}")

    return agent_id


# ─── CLI ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Bootstrap de Managed Agent en Anthropic. Crea el agent con su "
            "system prompt y tool definitions, persiste el agent_id en el "
            "config.json del cliente."
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
        help="Nombre del agente en snake_case.",
    )
    parser.add_argument(
        "--prompt-dir",
        default="system_prompts",
        help="Directorio con los static system prompts (.md). Default: system_prompts/",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Sobrescribe agent_id existente. Re-crea el agent en Anthropic.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No llama a Anthropic. Imprime el prompt construido para revisarlo.",
    )

    args = parser.parse_args()

    try:
        agent_id = bootstrap(
            client_id=args.client,
            agent_name=args.agent,
            prompt_dir=REPO_ROOT / args.prompt_dir,
            force=args.force,
            dry_run=args.dry_run,
        )
    except Exception as e:
        log.error(f"Bootstrap falló: {type(e).__name__}: {e}")
        sys.exit(1)

    print("\n" + "=" * 70)
    print("✅ Bootstrap completado")
    print(f"   Client:   {args.client}")
    print(f"   Agent:    {args.agent}")
    print(f"   AgentID:  {agent_id}")
    print("=" * 70)


if __name__ == "__main__":
    main()
