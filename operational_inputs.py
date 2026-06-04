"""
operational_inputs.py — Capa de parámetros operativos (DEC_075).

Lee el workbook operativo del cliente (budget / kpis / naming_utm) por Sheets API
y resuelve los valores vigentes para la ejecución actual del agente. READ-ONLY:
el agente NUNCA escribe en el workbook.

Diseño:
- Schema-driven y client-agnostic. Cliente N+1 = nuevo file_id en config, sin tocar código.
- Resolución most-specific-wins en 'nivel': plataforma concreta > cuenta > '*'.
- El modelo de budget dinámico (base + incremental_max, floors 5x/3x, floor blended)
  se RECALCULA en código a partir de los importes y floors — no se confía en el valor
  cacheado de la fórmula del Sheet (single source = importes + floors).
- Fallback explícito a los defaults del config si el workbook no está disponible o
  falta la fila del periodo; siempre se señala la fuente en el trace (gate 3.2).

Requiere: google-api-python-client, google-auth. La CF corre como la SA
llyc-agents-sa@llyc-ai-first-core; el Sheet debe estar compartido como Viewer con ella.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Optional
from zoneinfo import ZoneInfo

import google.auth
from googleapiclient.discovery import build

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
TABS = ("_meta", "kpis", "budget", "naming_utm")
_TRUE = {"true", "verdadero", "1", "si", "sí", "yes", "x"}
_ACCOUNT = ("*", "cuenta", "account")


# ----------------------------- coerciones -----------------------------

def _num(v: Any) -> Optional[float]:
    # Camino feliz: con valueRenderOption=UNFORMATTED_VALUE las celdas numéricas
    # llegan como int/float aunque el Sheet las MUESTRE como "18.000 €" o "5,00x"
    # (eso es formato de celda, no contenido). El bloque de texto de abajo es
    # defensa por si un humano teclea el valor como texto literal.
    if v is None or v == "" or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lower()
    for ch in ("€", "x", "%", " ", "\u00a0"):
        s = s.replace(ch, "")
    if not s:
        return None
    # Separador decimal europeo: "1.234,56" -> "1234.56" · "5,00" -> "5.00".
    # OJO: importes en miles SIN coma decimal ("18.000") son ambiguos y NO se
    # desambiguan aquí — el contrato del workbook exige que base/incremental/floors
    # sean numéricos (no texto). El smoke test (gate 3.2) lo valida.
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _b(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in _TRUE


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


# ----------------------------- resolución -----------------------------

def _level_rank(nivel: str) -> int:
    n = _s(nivel).lower()
    if n in ("", "*"):
        return 0
    if n in ("cuenta", "account"):
        return 1
    return 2  # plataforma concreta (meta, google_ads, ...)


def _level_matches(nivel: str, platform: Optional[str]) -> bool:
    n = _s(nivel).lower()
    if n in _ACCOUNT:
        return True
    return platform is not None and n == platform.lower()


def _period_matches(periodo: str, target: Optional[str]) -> bool:
    p = _s(periodo).lower()
    if p in ("", "*") or target is None:
        return True
    return p == target.lower()


def _best(rows: list[dict], platform: Optional[str]) -> Optional[dict]:
    cands = [r for r in rows if _level_matches(r.get("nivel"), platform)]
    return max(cands, key=lambda r: _level_rank(r.get("nivel"))) if cands else None


# ----------------------------- lectura Sheet -----------------------------

def _rows_to_dicts(values: list[list]) -> list[dict]:
    if not values:
        return []
    headers = [_s(h) for h in values[0]]
    out = []
    for raw in values[1:]:
        d = {h: (raw[i] if i < len(raw) else None) for i, h in enumerate(headers)}
        if any(_s(v) for v in d.values()):
            out.append(d)
    return out


def _read_workbook(file_id: str) -> dict[str, list[dict]]:
    creds, _ = google.auth.default(scopes=[SHEETS_SCOPE])
    svc = build("sheets", "v4", credentials=creds, cache_discovery=False)
    meta = svc.spreadsheets().get(
        spreadsheetId=file_id, fields="sheets.properties.title"
    ).execute()
    present = {s["properties"]["title"] for s in meta.get("sheets", [])}
    ranges = [f"{t}!A1:Z2000" for t in TABS if t in present]
    resp = svc.spreadsheets().values().batchGet(
        spreadsheetId=file_id, ranges=ranges,
        valueRenderOption="UNFORMATTED_VALUE", majorDimension="ROWS",
    ).execute()
    requested = [t for t in TABS if t in present]
    out = {t: [] for t in TABS}
    for tab, vr in zip(requested, resp.get("valueRanges", [])):
        out[tab] = _rows_to_dicts(vr.get("values", []))
    return out


# ----------------------------- modelo -----------------------------

@dataclass
class OperationalInputs:
    month: str
    currency: str = "EUR"
    budget: dict = field(default_factory=dict)        # {nivel: {...}}, incl. 'cuenta'
    kpis: list[dict] = field(default_factory=list)     # filas resueltas (enabled)
    naming_utm: dict = field(default_factory=dict)     # {plataforma: {...}}
    trace: dict = field(default_factory=dict)          # fuente, fallback, file_id, leído

    def kpi(self, metrica: str, parametro: str, platform: Optional[str] = None,
            periodo: Optional[str] = None) -> Optional[float]:
        rows = [r for r in self.kpis
                if _s(r["metrica"]).lower() == metrica.lower()
                and _s(r["parametro"]).lower() == parametro.lower()
                and _period_matches(r.get("periodo"), periodo)]
        best = _best(rows, platform)
        return _num(best["valor"]) if best else None

    def budget_for(self, platform: Optional[str] = None) -> Optional[dict]:
        return self.budget.get((platform or "cuenta").lower()) or self.budget.get("cuenta")


def _budget_block(row: dict) -> dict:
    base = _num(row.get("base_eur")) or 0.0
    incr = _num(row.get("incremental_max_eur")) or 0.0
    fb = _num(row.get("roas_floor_base"))
    fi = _num(row.get("roas_floor_incremental"))
    total = base + incr
    # floor blended recalculado, no se confía en el valor cacheado del Sheet
    blended = (base * fb + incr * fi) / total if total and fb is not None and fi is not None else None
    return {
        "nivel": _s(row.get("nivel")) or "cuenta",
        "base_eur": base, "incremental_max_eur": incr, "total_max_eur": total,
        "roas_floor_base": fb, "roas_floor_incremental": fi,
        "roas_blended_floor": round(blended, 2) if blended is not None else None,
    }


def _resolve(wb: dict[str, list[dict]], month: str,
             platforms: list[str]) -> tuple[dict, list[dict], dict, str]:
    # budget: fila del mes actual, por nivel cuenta + cada plataforma pedida
    bud_rows = [r for r in wb["budget"] if _b(r.get("enabled")) and _s(r.get("mes")) == month]
    budget = {}
    acc = _best(bud_rows, None)
    if acc:
        budget["cuenta"] = _budget_block(acc)
    for p in platforms:
        row = _best([r for r in bud_rows if _level_rank(r.get("nivel")) == 2
                     and _s(r.get("nivel")).lower() == p.lower()], p)
        if row:
            budget[p.lower()] = _budget_block(row)
    # kpis: todas las filas enabled (la resolución se hace on-demand vía .kpi())
    kpis = [r for r in wb["kpis"] if _b(r.get("enabled"))]
    # naming_utm por plataforma
    naming = {_s(r.get("plataforma")).lower(): r for r in wb["naming_utm"] if _b(r.get("enabled"))}
    currency = next((_s(r.get("value")) for r in wb["_meta"] if _s(r.get("key")) == "currency"), "EUR")
    return budget, kpis, naming, currency or "EUR"


# ----------------------------- API pública -----------------------------

def load_operational_inputs(client_config: dict, agent_name: str,
                            platforms: Optional[list[str]] = None,
                            now: Optional[_dt.datetime] = None) -> OperationalInputs:
    """
    Punto de entrada. Llamar tras cargar config/secrets y antes de construir el prompt.
    Inyectar to_prompt_block(oi) en el system prompt y volcar oi.trace al log de la ejecución.
    """
    oi_cfg = (client_config.get("operational_inputs") or {})
    file_id = (oi_cfg.get("workbook") or {}).get("file_id")
    tz = ZoneInfo((oi_cfg.get("timezone") or "Europe/Madrid"))
    now = now or _dt.datetime.now(tz)
    month = now.strftime("%Y-%m")
    platforms = [p.lower() for p in (platforms or [])]

    trace = {"file_id": file_id, "read_at": now.isoformat(), "source": "workbook",
             "fallback_used": False, "warnings": []}

    if not file_id:
        return _from_fallback(oi_cfg, month, trace, "config sin operational_inputs.workbook.file_id")

    try:
        wb = _read_workbook(file_id)
    except Exception as e:  # red, permisos, Sheet inaccesible
        return _from_fallback(oi_cfg, month, trace, f"workbook ilegible: {type(e).__name__}: {e}")

    budget, kpis, naming, currency = _resolve(wb, month, platforms)
    if "cuenta" not in budget:
        # sin fila de budget del mes → fallback de budget (bloque), KPIs sí del workbook
        fb = (oi_cfg.get("fallback") or {}).get("budget")
        if fb:
            budget["cuenta"] = _budget_block({**fb, "nivel": "cuenta"})
            trace["fallback_used"] = True
            trace["warnings"].append(f"sin fila budget para {month}; usado fallback de config")
        else:
            trace["warnings"].append(f"sin fila budget para {month} y sin fallback en config")

    return OperationalInputs(month=month, currency=currency, budget=budget,
                             kpis=kpis, naming_utm=naming, trace=trace)


def _from_fallback(oi_cfg: dict, month: str, trace: dict, reason: str) -> OperationalInputs:
    fb = oi_cfg.get("fallback") or {}
    trace.update(source="config_fallback", fallback_used=True)
    trace["warnings"].append(reason)
    budget = {"cuenta": _budget_block({**(fb.get("budget") or {}), "nivel": "cuenta"})} if fb.get("budget") else {}
    kpis = [r for r in (fb.get("kpis") or []) if _b(r.get("enabled", True))]
    return OperationalInputs(month=month, currency=_s(fb.get("currency")) or "EUR",
                             budget=budget, kpis=kpis, trace=trace)


def to_prompt_block(oi: OperationalInputs) -> str:
    """Bloque inyectable en el system prompt. El agente razona con estos valores."""
    lines = [
        "## PARÁMETROS OPERATIVOS VIGENTES (fuente: workbook operativo, DEC_075)",
        f"Mes: {oi.month} · Moneda: {oi.currency} · Fuente: {oi.trace.get('source')}",
    ]
    if oi.trace.get("fallback_used"):
        lines.append("AVISO: algún valor proviene del FALLBACK de config (el workbook no estaba "
                     "disponible o faltaba la fila). Señálalo explícitamente en el output.")
    acc = oi.budget.get("cuenta")
    if acc:
        lines.append(
            f"Budget (cuenta): base {acc['base_eur']:.0f}{oi.currency} + incremental_max "
            f"{acc['incremental_max_eur']:.0f}{oi.currency} = total_max {acc['total_max_eur']:.0f}{oi.currency}. "
            f"Floors: base {acc['roas_floor_base']}x, incremental {acc['roas_floor_incremental']}x, "
            f"blended {acc['roas_blended_floor']}x (ROAS mínimo que justifica el total)."
        )
    for p, blk in oi.budget.items():
        if p != "cuenta":
            lines.append(f"Budget ({p}): total_max {blk['total_max_eur']:.0f}{oi.currency}, "
                         f"floor blended {blk['roas_blended_floor']}x.")
    if oi.kpis:
        lines.append("Tolerancias y referencias (most-specific-wins por plataforma):")
        for r in oi.kpis:
            lvl = _s(r.get("nivel")) or "cuenta"
            lines.append(f"  - [{lvl}] {_s(r.get('metrica'))}.{_s(r.get('parametro'))} = "
                         f"{_s(r.get('valor'))} (ventana {_s(r.get('ventana')) or 'n/a'})")
    return "\n".join(lines)


def reference_used(oi: OperationalInputs) -> dict:
    """Resumen para el log/output de la ejecución (gate de validación 3.2)."""
    return {
        "month": oi.month, "source": oi.trace.get("source"),
        "fallback_used": oi.trace.get("fallback_used"),
        "budget_cuenta": oi.budget.get("cuenta"),
        "kpis_count": len(oi.kpis), "warnings": oi.trace.get("warnings"),
        "file_id": oi.trace.get("file_id"),
    }
