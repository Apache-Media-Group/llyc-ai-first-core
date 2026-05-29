"""
tools/email.py — Renderizado HTML de notificaciones por agente.

Owner: Max (Massimiliano Turinetto) · Reviewer: Alberto González
Sprint: 1 (introducido con DEC_050 / cierre funcional performance-monitor V&V)

Función pública única: render_email_html(template_name, context) -> str.
Carga templates desde email_templates/ al root del repo (al mismo nivel
que tools/, system_prompts/, clients/).

Pattern: Jinja2 con autoescape HTML + StrictUndefined para fallar ruidosamente
si un template referencia una variable inexistente en el contexto. Cada
agente define su propio email_templates/<agent_key>.html que extiende
email_templates/_base.html con blocks específicos.

Decisiones aplicadas:
  - DEC_050: email HTML con triangulación 3-way Shopify ↔ GA4 ↔ paid.
  - Patrón estándar cross-agent: weekly-digest reutilizará este renderer
    + extenderá _base.html con su propio template hijo (sin tocar este módulo).

Sin side effects al import — Environment se crea lazy en el primer uso
(evita coste al boot de la Cloud Function si el agente no envía email).
"""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape


_TEMPLATES_DIR = Path(__file__).parent.parent / "email_templates"
_env: Environment | None = None


def _get_env() -> Environment:
    """Singleton Jinja2 Environment (lazy)."""
    global _env
    if _env is None:
        _env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
    return _env


def render_email_html(template_name: str, context: dict[str, Any]) -> str:
    """
    Renderiza un template HTML del directorio email_templates/.

    Args:
        template_name: nombre relativo a email_templates/.
                       Ej. 'performance_monitor.html'.
        context: dict con las variables a inyectar en el template.

    Returns:
        HTML renderizado como string, listo para pasar al body_html de
        notifications.send_alert_email().

    Raises:
        jinja2.TemplateNotFound: si el template no existe en email_templates/.
        jinja2.UndefinedError: si el template referencia variables ausentes
            del contexto (StrictUndefined). Comportamiento DELIBERADO —
            forzar a que el contrato template↔código se rompa de forma
            visible en lugar de generar emails con campos vacíos.
    """
    env = _get_env()
    template = env.get_template(template_name)
    return template.render(**context)
