#!/usr/bin/env python3
"""engine.py — motor de referencia del generador. Consume grammar (git) + compiled.json (sync).
Lo porta CC a engine.ts 1:1. No contiene vocabulario hardcoded."""
import re, json, yaml, pathlib
BASE = pathlib.Path(__file__).parent

class Engine:
    def __init__(self, compiled_path=None):
        self.g = yaml.safe_load((BASE / "grammar/naming-grammar.yaml").read_text())
        compiled_path = pathlib.Path(compiled_path) if compiled_path else (BASE / "compiled.json")
        self.c = json.loads(compiled_path.read_text())
        self.block_re = re.compile(self.g["block_regex"])
        self.pairs = {tuple(p) for p in self.c["canal_platform"]}
        self.legacy = self.c.get("legacy", {})

    def legacy_token(self, scope, value):
        return self.legacy.get(scope, {}).get(value, value)

    # --- flujo D: corregir una UTM existente ---
    def diagnose_utm(self, raw_source, raw_medium):
        s = self.legacy_token("utm_source", raw_source.strip().lower())
        m = self.legacy_token("utm_medium", raw_medium.strip().lower())
        changed = (s != raw_source.strip().lower()) or (m != raw_medium.strip().lower())
        return s, m, changed

    # --- flujo D: diagnosticar/corregir un nombre existente (legacy) ---
    def diagnose_name(self, client, level, raw_name, ctx=None):
        inst = self.c["instances"][client]
        order = self.g["levels"][level]["backbone"] + [e["nombre"] for e in self.exts_for(inst, level)]
        parts = raw_name.strip().lower().split("_")
        if len(parts) != len(order):
            return {"name": None, "diff": [], "structural": f"aridad {len(parts)} != {len(order)} (esperado {order})"}, ["aridad estructural"]
        corrected, diff = {}, []
        for blk, raw in zip(order, parts):
            v = self.legacy_token("utm_source", raw) if blk == "plataforma" else raw
            corrected[blk] = v
            diff.append({"block": blk, "raw": raw, "value": v, "changed": v != raw})
        name, errs = self.build(client, level, corrected, ctx)
        return {"name": name, "tokens": corrected, "diff": diff}, errs

    # --- validación de un token contra su diccionario ---
    def token_valid(self, block, value, ctx, inst):
        if value == self.g["sentinel"]:
            return self.g["x_allowed"].get(block, False)
        if not self.block_re.match(value):
            return False
        if block == "cliente":
            return value == inst["cliente_code"]
        if block == "creativo":
            return value in inst["creativo"]
        b = self.c["vocab"].get(block, {})
        if any(value.startswith(p) and len(value) > len(p) for p in b.get("prefixes", [])):
            return True
        if any(re.match(p, value) for p in b.get("patterns", [])):
            return True
        cond = self.g.get("conditional", {})
        if block in cond:
            parent_val = ctx.get(cond[block])
            return value in b.get("by_parent", {}).get(parent_val, [])
        return value in b.get("values", [])

    def exts_for(self, inst, level):
        return [e for e in inst["extensions"] if e["nivel"] == level]

    # --- construye y valida el nombre de un nivel ---
    def build(self, client, level, tokens, ctx=None):
        ctx = ctx or {}
        inst = self.c["instances"][client]
        backbone = self.g["levels"][level]["backbone"]
        exts = self.exts_for(inst, level)
        order = backbone + [e["nombre"] for e in exts]
        errs, parts = [], []
        if set(tokens) != set(order):
            errs.append(f"aridad: esperados {order}, recibidos {list(tokens)}")
        ctx2 = {"pais": tokens.get("pais", ctx.get("pais")),
                "plataforma": tokens.get("plataforma", ctx.get("plataforma"))}
        for blk in order:
            val = tokens.get(blk, "<MISSING>")
            ex = next((e for e in exts if e["nombre"] == blk), None)
            if ex:
                if val not in ex["vocabulario"]:
                    errs.append(f"{blk}='{val}' fuera de extension {ex['vocabulario']}")
            elif not self.token_valid(blk, val, ctx2, inst):
                errs.append(f"{blk}='{val}' invalido")
            parts.append(val)
        if level == "campaign" and "canal" in tokens and "plataforma" in tokens:
            if (tokens["canal"], tokens["plataforma"]) not in self.pairs:
                errs.append(f"par invalido: canal '{tokens['canal']}' no admite plataforma '{tokens['plataforma']}'")
        return "_".join(parts), errs

    # --- parsea un nombre de ancla existente (flujos B/C) ---
    def parse(self, client, level, name, ctx=None):
        inst = self.c["instances"][client]
        order = self.g["levels"][level]["backbone"] + [e["nombre"] for e in self.exts_for(inst, level)]
        parts = name.split("_")
        if len(parts) != len(order):
            return None, [f"ancla {level}: aridad {len(parts)} != esperada {len(order)}"]
        tokens = dict(zip(order, parts))
        _, errs = self.build(client, level, tokens, ctx)
        return tokens, errs

    # --- reconstrucción UTM ---
    def _ga4_linked(self, client, plataforma):
        for p in self.c["instances"][client]["platforms"]:
            if p["name"] == plataforma:
                return p.get("ga4_linked", True)
        return True

    # --- reconstrucción UTM (set GA4 completo; macros por plataforma) ---
    def utm(self, client, plataforma, campaign, group, ad, utm_id=None, destino_web=True):
        r = self.c["utm_rules"].get(plataforma)
        if not r: return f"[sin regla UTM para {plataforma}]"
        if not destino_web:
            return "[destino no-web (perfil social / app store) — UTM N/A]"
        mode = r["mode"]
        camp = r.get("campaign_macro") or campaign            # macro de plataforma o literal
        uid = r.get("id_macro") or utm_id or campaign         # macro de id, override, o nombre
        if mode == "none":
            return f"[{plataforma}: atribucion sin URL params]"
        if mode == "autotag":
            if self._ga4_linked(client, plataforma):
                return f"[AUTO-TAGGING {r['clickid']} — sin UTM manual; final_url limpia]"
            return (f"[AUTO-TAGGING {r['clickid']} — cuenta NO vinculada a GA4: añadir solo]"
                    f" ?utm_campaign={camp}&utm_id={uid}")
        # manual o sdf
        if r.get("content_macro"):
            content = r["content_macro"]
        else:
            content = {"group_ad": f"{group}_{ad}", "group": group}.get(r["content"], r["content"])
        return (f"utm_source={r['utm_source']}&utm_medium={r['utm_medium']}"
                f"&utm_campaign={camp}&utm_id={uid}&utm_source_platform={plataforma}"
                f"&utm_content={content}")
