# ================================================================
# PLATFORM CONFIG — derivación de plataformas/tablas desde config
# ================================================================
# Lógica PURA: no toca GCP, no tiene side-effects de import.
# main.py la usa en runtime; el test de paridad la importa sin
# credenciales para demostrar el no-op de LCDC (DEC_024 / DEC_089).
#
# Contrato de config (bloque dashboard del config.json del cliente):
#   - datasources: lista de plataformas activas (identificadores, lower-case)
#   - table_map:   mapa {plataforma-display -> tabla BQ}. Sus CLAVES definen
#                  el nombre-display y el ORDEN de las plataformas del cliente.
# El onboarding de plataformas nuevas = editar esta config, no tocar código.
# ================================================================


def _require_table_map(dashboard_cfg: dict) -> dict:
    """
    Devuelve el table_map del cliente. Fail-loud si falta y hay datasources:
    sin mapa no se puede resolver ninguna tabla (mejor error que silencio).
    """
    table_map = dashboard_cfg.get("table_map")
    datasources = dashboard_cfg.get("datasources", [])
    if not isinstance(table_map, dict) or not table_map:
        if datasources:
            raise ValueError(
                "dashboard.table_map ausente o vacío pero datasources no está vacío: "
                f"{datasources}. Añade table_map (plataforma -> tabla) al config del cliente."
            )
        return {}
    return table_map


def get_active_platforms(dashboard_cfg: dict) -> list:
    """
    Plataformas activas del cliente, en el orden y casing de las claves de
    table_map, filtradas por datasources (match case-insensitive).

    No-op frente al código antiguo: reproduce byte a byte el
    `[p for p in PLATFORMS if p.lower() in datasources]`, donde PLATFORMS pasa
    a ser `list(table_map.keys())`.

    Fail-loud: cualquier datasource sin entrada en table_map -> ValueError con
    el nombre del datasource (nunca se ignora en silencio).
    """
    table_map = _require_table_map(dashboard_cfg)
    datasources = [s.lower() for s in dashboard_cfg.get("datasources", [])]

    known = {k.lower() for k in table_map}
    missing = [d for d in datasources if d not in known]
    if missing:
        raise ValueError(
            f"datasource(s) sin entrada en dashboard.table_map: {missing}. "
            f"Plataformas mapeadas: {sorted(table_map)}."
        )

    return [p for p in table_map if p.lower() in datasources]


def resolve_table(platform: str, table_map: dict) -> str | None:
    """Tabla BQ para una plataforma-display, o None si no está mapeada."""
    return table_map.get(platform)
