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

---

## Runbook Operativo — DV360 Write Scripts

### SA y credenciales

- **SA de escritura:** `llyc-ops-writer-sa@llyc-ai-first-core.iam.gserviceaccount.com`
- **Secret:** `DV360_OPS_WRITER_SA_KEY` en Secret Manager de `llyc-ai-first-core`
- **Política de guardrails:** pestaña `dv360_write_policy` del workbook operativo del cliente

### Convención de uso

```bash
python scripts/dv360/<área>/<script>.py \
  --client <client_id> \
  [--dry-run] \
  [parámetros específicos]
```

- `--client` — siempre obligatorio.
- `--dry-run` — simula sin ejecutar. Usar siempre antes de la primera ejecución real.
- `--reason` — obligatorio cuando se usa `--skip-guardrail` o `--max-bid` con valor superior al defecto.

### Override de guardrails

```bash
python scripts/dv360/line_items/update_bid.py \
  --client vidal-vidal \
  --line-item-id 12345 \
  --bid-eur 75.00 \
  --max-bid 100.00 \
  --reason "Puja especial Black Friday aprobada por Jesús el 2026-11-01"
```

El `--reason` queda registrado en el audit log de Cloud Logging.

### Flujo completo de creación

Todos los objetos se crean en **DRAFT**. Activar solo tras revisión.

### Política de guardrails

Límites leídos en runtime de la pestaña `dv360_write_policy` del workbook del cliente:

| Parámetro | Descripción |
|---|---|
| `max_bid_eur` | Puja máxima sin override |
| `max_budget_variation_pct` | Variación máxima de presupuesto diario |
| `max_budget_eur_io` | Presupuesto máximo por IO |
| `max_budget_eur_li` | Presupuesto máximo por LI |
| `allowed_operations` | Operaciones permitidas para este cliente |
| `require_reason_on_override` | Si True, `--reason` obligatorio en overrides |

Si falta la fila en el workbook, el script aplica defaults conservadores. Nunca opera sin límite.