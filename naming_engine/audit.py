"""audit.py — núcleo de auditoría compartido (decisión a, DEC_094).
El auditor v4.0 NO reimplementa reglas: delega en el MISMO engine que el generador,
leyendo el MISMO compiled.json. Esta es la función que invocarán sus tools.
"""
from urllib.parse import urlparse, parse_qs
from .engine import Engine

class Auditor:
    def __init__(self, compiled_path=None):
        self.E = Engine(compiled_path=compiled_path)

    def _domain_of(self, url):
        try: return (urlparse(url).hostname or "").lower().lstrip("www.")
        except Exception: return ""

    def _is_client_landing(self, client, url):
        if not url: return False
        host = self._domain_of(url)
        return any(host == d or host.endswith("." + d) for d in self.E.c["instances"][client]["domains"])

    def audit_naming(self, client, level, name):
        """[] = conforme; lista de (NAMING_INCORRECT, detalle) si incumple."""
        if not name:
            return []  # nivel sin nombre (Google RSA/Shopping) — se omite
        _, errs = self.E.parse(client, level, name)
        return [("NAMING_INCORRECT", e) for e in errs]

    def audit_utm(self, client, plataforma, destination_url, url_tags, campaign, group, ad):
        """[] = conforme o N/A; si no, lista de (UTM_MISSING|UTM_INCORRECT, detalle).
        Trackabilidad se decide por destination_url (dominio/boosting);
        la forma de la UTM se audita sobre url_tags (plantilla cruda, macros sin resolver)."""
        # 1. Trackabilidad: sin destino (boosting/interacción) o destino no-web → N/A
        if not destination_url:
            return []  # boosting puro / sin landing — UTM no aplica
        if not self._is_client_landing(client, destination_url):
            return []  # destino no-web (perfil social / app store) — UTM no aplica

        expected = self.E.utm(client, plataforma, campaign, group, ad)
        # 2. Autotag vinculada (Google/Bing): se espera URL limpia, sin UTM manual
        if expected.startswith("[AUTO-TAGGING") and "sin UTM manual" in expected:
            has_manual = bool(url_tags) and "utm_" in url_tags
            if has_manual:
                return [("UTM_INCORRECT", "cuenta vinculada a GA4 → retirar UTM manual (autotag GCLID)")]
            return []
        # 3. Landing del cliente sin plantilla de tags → tracking ausente
        if not url_tags:
            return [("UTM_MISSING", "landing del cliente sin parámetros UTM (url_tags vacío)")]
        # 4. Forma macro: comparar la plantilla cruda contra el set GA4 esperado
        params = {k: v[0] for k, v in parse_qs(url_tags.lstrip("?")).items()}
        exp = {kv.split("=")[0].lstrip("?"): kv.split("=", 1)[1]
               for kv in expected.split("&") if "=" in kv}
        errs = []
        for key in ("utm_source", "utm_medium", "utm_id", "utm_source_platform", "utm_content"):
            if key not in params:
                errs.append(("UTM_MISSING", f"{key} ausente (set GA4 v2.1)"))
            elif key in ("utm_source", "utm_medium") and params[key] != exp.get(key):
                errs.append(("UTM_INCORRECT", f"{key}='{params[key]}' — esperado '{exp.get(key)}'"))
            elif key == "utm_content" and params[key] != exp.get(key):
                errs.append(("UTM_INCORRECT", f"utm_content='{params[key]}' — esperado forma macro '{exp.get(key)}'"))
        return errs
