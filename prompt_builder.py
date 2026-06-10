"""
prompt_builder.py — Construcción del system prompt de los agentes.

Aislado de main.py para evitar el side effect de
google.cloud.logging.Client().setup_logging() (CloudLoggingHandler).
Cualquier script que necesite construir el system prompt de un agente
importa desde aquí sin contaminar el logging global del proceso.

Decisiones aplicadas:
  - DEC_059: filtrado de plataformas inyectadas por enabled + tools del agente
  - DEC_065: construcción client-side en runtime (no Managed Agents)
"""

import json
from pathlib import Path

from tools.definitions import get_tool_definitions


def load_static_prompt(agent_name: str) -> str:
    """Lee el static system prompt desde system_prompts/<agent>.md (snake_case)."""
    agent_key = agent_name.replace("-", "_")
    path = Path(__file__).parent / "system_prompts" / f"{agent_key}.md"
    if not path.exists():
        raise FileNotFoundError(f"System prompt no encontrado: {path}")
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"System prompt vacío: {path}")
    return content


def build_dynamic_context(config: dict, agent_name: str) -> str:
    """
    Construye la sección 'CONTEXTO DEL CLIENTE' inyectable al system prompt.
    DEC_059: filtra plataformas por enabled + tools disponibles para el agente.
    DEC_065: construcción client-side en runtime.
    DEC_081: budget, tolerancias y KPIs de referencia ya NO se construyen desde
    config — son fuente única del workbook operativo (to_prompt_block(oi), DEC_075),
    inyectado por separado en main.py. Aquí solo queda contexto identitario estable.
    """
    agent_key = agent_name.replace("-", "_")
    client = config["client"]
    platforms = config["platforms"]
    agent_cfg = config["agents"][agent_key]
    notifications_cfg = config.get("notifications", {})

    # DEC_059: solo plataformas enabled Y con tool disponible para este agente
    tool_names_for_agent = {t["name"] for t in get_tool_definitions(agent_key)}
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

## Plataformas activas e identificadores
```json
{platforms_json}
```

## Output
- Carpeta destino en Drive: {agent_cfg['output_folder']}
- Schedule: {agent_cfg['schedule']}

## Notificaciones
- Canal: {notifications_cfg.get('canal', 'email')}
- Destinatarios: {notifications_cfg.get('alert_recipients', [])}
- Dispara en STATUS: {notifications_cfg.get('alert_levels', ['ALERTA', 'ERROR'])}
""".rstrip()
