# scripts/dv360 — Catálogo de scripts de escritura DV360

Catálogo de scripts manuales para operaciones de escritura sobre DV360 (DEC_069, DEC_084).

## Principios

- **Un script = una acción operativa.** No hay scripts multi-función.
- **SA dedicada:** `llyc-ops-writer-sa` (DEC_084). NUNCA `llyc-agents-sa`.
- **Dry-run obligatorio** antes de ejecutar en producción: `--dry-run`
- **Confirmación interactiva** en todas las acciones. Doble confirmación en acciones destructivas.
- **Auditoría** en Cloud Logging estructurado por cada ejecución.

## Prerequisitos

```bash
# Variable de entorno con tu identidad (para auditoría)
export LLYC_OPERATOR=tu.nombre@llyc.global

# Credenciales GCP (Application Default Credentials)
gcloud auth application-default login
```

## Uso general

```bash
# Siempre primero con --dry-run para ver qué haría
python scripts/dv360/line_items/pause_line_item.py \
  --client vidal-vidal \
  --line-item-id 123456789 \
  --dry-run

# Ejecutar tras confirmar el dry-run
python scripts/dv360/line_items/pause_line_item.py \
  --client vidal-vidal \
  --line-item-id 123456789
```

## Estructura

```
scripts/dv360/
├── README.md                    # Este fichero
├── _common/
│   ├── auth.py                  # SA escritura + lectura de advertiser_id desde config
│   └── audit.py                 # Logging estructurado + confirmación interactiva
├── line_items/
│   ├── pause_line_item.py       # Tier 1
│   ├── activate_line_item.py    # Tier 1
│   ├── update_bid.py            # Tier 1 — guardrail 50 EUR max
│   └── update_daily_budget.py   # Tier 1 — guardrail 20% max variación
└── insertion_orders/
    ├── pause_io.py              # Tier 1
    └── activate_io.py           # Tier 1
```

## Decisiones de referencia

- DEC_022 — El agente es read-only. Los scripts son la vía de escritura supervisada.
- DEC_069 — Separación formal agente / scripts manuales.
- DEC_083 — DV360 vía API directa (mismo cliente que tools/dv360.py).
- DEC_084 — SA separada `llyc-ops-writer-sa` para escritura.
