"""
test_platform_parity.py — Garantía de no-op del refactor PLATFORMS/TABLE_MAP.

El dashboard campaign-intelligence dejó de hardcodear el set de plataformas de
LCDC en main.py: ahora se derivan de config.dashboard (datasources + table_map)
vía platform_config.py (lógica pura). Este test demuestra que la derivación
desde clients/lcdc/config.json produce EXACTAMENTE el mismo output que el código
antiguo (golden fixture congelado) — el no-op a nivel de código exigido por el
spec §7. Mismo patrón que test_naming_parity.py.

Cubre el nivel de código; la validación E2E real contra datos de LCDC es
sign-off humano (spec §11), no la cubre este test.
"""

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
API_DIR = REPO / "dashboards" / "campaign-intelligence" / "api"
LCDC_CONFIG = REPO / "clients" / "lcdc" / "config.json"
GOLDEN = REPO / "tests" / "fixtures" / "lcdc_platforms_golden.json"

# platform_config es lógica pura (sin side-effects GCP) — importable en test.
# Importar main.py NO es posible aquí: crea logging + BigQuery client en import.
sys.path.insert(0, str(API_DIR))
import platform_config  # noqa: E402


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _lcdc_dashboard_cfg():
    return _load(LCDC_CONFIG)["dashboard"]


def test_fixtures_present():
    assert LCDC_CONFIG.exists(), "falta clients/lcdc/config.json"
    assert GOLDEN.exists(), "falta el golden fixture de paridad de plataformas"


def test_active_platforms_parity():
    """get_active_platforms derivado === golden pre-refactor (orden + casing)."""
    golden = _load(GOLDEN)["active_platforms"]
    derived = platform_config.get_active_platforms(_lcdc_dashboard_cfg())
    assert derived == golden, (
        "las plataformas activas derivadas de config divergen del comportamiento "
        "pre-refactor de LCDC — el refactor NO es no-op"
    )


def test_table_map_parity():
    """El table_map efectivo de LCDC === TABLE_MAP hardcodeado antiguo."""
    golden = _load(GOLDEN)["table_map"]
    cfg_table_map = _lcdc_dashboard_cfg()["table_map"]
    assert cfg_table_map == golden, (
        "el table_map de clients/lcdc/config.json diverge del TABLE_MAP "
        "hardcodeado original — el refactor NO es no-op"
    )
    # Resolución tabla-a-tabla idéntica para cada plataforma activa.
    for platform in golden:
        assert (
            platform_config.resolve_table(platform, cfg_table_map) == golden[platform]
        )


def test_missing_table_map_entry_fails_loud():
    """Un datasource sin entrada en table_map -> ValueError, nunca silencio."""
    bad_cfg = {
        "datasources": ["spotify", "cm360"],
        "table_map": {"Spotify": "Spotify_native"},
    }
    with pytest.raises(ValueError, match="cm360"):
        platform_config.get_active_platforms(bad_cfg)


def test_missing_table_map_with_datasources_fails_loud():
    """datasources no vacío sin table_map -> ValueError explícito."""
    with pytest.raises(ValueError, match="table_map"):
        platform_config.get_active_platforms({"datasources": ["meta"]})


def test_empty_dashboard_is_inert():
    """Sin datasources ni table_map -> sin plataformas activas, sin error."""
    assert platform_config.get_active_platforms({}) == []
