"""
audit_assembler.py — Ensamblador determinista del naming-utm-auditor v4.0.

Convergencia DEC_096: el veredicto de naming/UTM lo da el motor compartido
(naming_engine.audit.Auditor sobre el mismo compiled.json que el generador).
Este módulo NO reimplementa reglas: recorre el inventario activo recuperado por
las tools de plataforma, delega cada veredicto en el Auditor, deduplica por
entidad, trunca a 20/plataforma con muestra representativa, deriva el modelo
dual de status (DEC_072) y monta el contrato JSON de salida (idéntico al de
v3.1 — backward-compatible: email y downstream no cambian).

READ-ONLY (DEC_022): detecta y describe. No decide, no prescribe, no escribe.
Sin LLM: 100% determinista (patrón perf-monitor L3, DEC>=084).
"""
from __future__ import annotations

from naming_engine.audit import Auditor

CAP = 20  # máximo de entradas por plataforma en errors[] (resto se trunca)
SEVERITY = {"UTM_MISSING": 0, "UTM_INCORRECT": 1, "NAMING_INCORRECT": 2}


def _entry(error_type, detail, *, ad_id=None, campaign="", group="", ad="", url=None, group_key="adset_name"):
    """Una entrada del array errors[]. group_key alterna adset_name/adgroup_name por plataforma."""
    e = {"ad_id": ad_id, "campaign_name": campaign, group_key: group,
         "ad_name": ad, "url": url, "error_type": error_type, "error_detail": detail}
    return e


def _truncate(errors):
    """Muestra representativa: ordena por severidad y reparte el cap entre tipos
    presentes (mínimo 3/tipo, o todos si hay menos). Devuelve (muestra, truncated)."""
    if len(errors) <= CAP:
        return errors, False
    by_type = {}
    for e in errors:
        by_type.setdefault(e["error_type"], []).append(e)
    types = sorted(by_type, key=lambda t: SEVERITY.get(t, 9))
    quota = max(3, CAP // len(types))
    sample = []
    for t in types:
        sample.extend(by_type[t][:quota])
    sample = sorted(sample, key=lambda e: SEVERITY.get(e["error_type"], 9))[:CAP]
    return sample, True


def audit_platform(auditor, client_code, plataforma, ads, group_key):
    """Audita el inventario de una plataforma. ads = lista de dicts del inventario
    (ad_id, ad_name, adset_name/adgroup_name, campaign_name, destination_url, url_tags).
    Devuelve (errors_full, total_ads, ads_con_error_a_nivel_ad)."""
    errors = []
    seen_campaign, seen_group = set(), set()
    ads_with_ad_level_error = set()

    for a in ads:
        camp = a.get("campaign_name") or ""
        grp = a.get(group_key) or a.get("adset_name") or a.get("adgroup_name") or ""
        adn = a.get("ad_name") or ""
        ad_id = a.get("ad_id")
        dest = a.get("destination_url")
        tags = a.get("url_tags")

        # NAMING campaña — dedup una por campaña
        if camp and camp not in seen_campaign:
            seen_campaign.add(camp)
            for et, det in auditor.audit_naming(client_code, "campaign", camp):
                errors.append(_entry(et, det, campaign=camp, group_key=group_key))

        # NAMING grupo — dedup una por (campaña, grupo)
        gk = (camp, grp)
        if grp and gk not in seen_group:
            seen_group.add(gk)
            for et, det in auditor.audit_naming(client_code, "group", grp):
                errors.append(_entry(et, det, campaign=camp, group=grp, group_key=group_key))

        # NAMING ad + UTM — por ad
        ad_errs = list(auditor.audit_naming(client_code, "ad", adn)) if adn else []
        ad_errs += auditor.audit_utm(client_code, plataforma, dest, tags, camp, grp, adn)
        for et, det in ad_errs:
            errors.append(_entry(et, det, ad_id=ad_id, campaign=camp, group=grp,
                                 ad=adn, url=dest, group_key=group_key))
        if ad_errs:
            ads_with_ad_level_error.add(ad_id)

    return errors, len(ads), len(ads_with_ad_level_error)


def assemble(client_name, client_code, analysis_date, compiled_path, inventories):
    """Monta el contrato JSON del auditor.
    inventories: {"meta": [...ads...], "google_ads": [...ads...]} (solo plataformas con datos;
    una plataforma con valor None = ERROR de fuente).
    """
    auditor = Auditor(compiled_path=compiled_path)
    group_keys = {"meta": "adset_name", "google_ads": "adgroup_name"}
    platform_client = {"meta": "meta", "google_ads": "google"}

    platforms = {}
    totals = {"total_active_ads": 0, "total_ads_with_errors": 0,
              "utm_missing": 0, "utm_incorrect": 0, "naming_incorrect": 0}
    any_alert = False

    for plat, ads in inventories.items():
        gk = group_keys[plat]
        if ads is None:  # fuente falló
            platforms[plat] = {"status": "ERROR", "total_active_ads": None,
                               "ads_with_errors": None, "errors_truncated": False,
                               "error_detail": "fuente no disponible", "errors": None}
            continue
        errors, total, ads_err = audit_platform(auditor, client_code, platform_client[plat], ads, gk)
        for e in errors:
            totals[{"UTM_MISSING": "utm_missing", "UTM_INCORRECT": "utm_incorrect",
                    "NAMING_INCORRECT": "naming_incorrect"}[e["error_type"]]] += 1
        sample, truncated = _truncate(errors)
        status = "ALERTA" if errors else "NORMAL"
        any_alert = any_alert or bool(errors)
        platforms[plat] = {"status": status, "total_active_ads": total,
                           "ads_with_errors": ads_err, "errors_truncated": truncated,
                           "error_detail": "", "errors": sample}
        totals["total_active_ads"] += total
        totals["total_ads_with_errors"] += ads_err

    exec_status = "PARTIAL" if any(p.get("status") == "ERROR" for p in platforms.values()) else "OK"
    analysis_status = "ALERTA" if any_alert else "NORMAL"

    n = totals["total_active_ads"]
    summary = (f"{n} ads activos auditados. {totals['total_ads_with_errors']} ads con errores: "
               f"{totals['utm_missing']} UTM_MISSING, {totals['utm_incorrect']} UTM_INCORRECT, "
               f"{totals['naming_incorrect']} NAMING_INCORRECT (deduplicado por entidad).")

    return {"agent": "naming-utm-auditor", "client": client_name, "date": analysis_date,
            "execution_status": exec_status, "execution_status_detail": "",
            "analysis_status": analysis_status, "summary": summary,
            "platforms": platforms, "totals": totals}
