# llyc-ai-first-core

Executor de herramientas y agentes del sistema **LLYC AI-First**: una capa agéntica propietaria sobre paid media, brand intelligence y customer data para las cuentas de LLYC.

El sistema **detecta, analiza y propone; nunca decide ni ejecuta** sobre plataforma (frontera dura, read-only a nivel software e IAM — DEC_022). La decisión y la ejecución son siempre humanas.

> Fuente de verdad técnica: `arquitectura-sistema.md` en el Drive **DM-AI-FIRST / 02_ARQUITECTURA**. Este README es el resumen operativo del repo; ante discrepancia, mandan ese doc y el `decision-log`.

---

## Qué es (y qué no es)

- **Es** un sistema de agentes de razonamiento sobre las APIs de paid media y la fuente de verdad de revenue de cada cliente, que produce diagnósticos y propuestas.
- **No es** automatización de tareas, ni un dashboard, ni un wrapper sobre un LLM, ni un sistema que ejecuta cambios en las plataformas.
- **Principio rector:** *un codebase, N configuraciones*. El sistema es común; el cliente es un parámetro. El cliente N+1 no debe requerir reescritura de código.

---

## Arquitectura

Tres capas:

1. **Inteligencia** — Claude API (razonamiento y propuesta).
2. **Herramientas** — `agent-executor`, una única Cloud Function que habla con Meta, Google Ads, GA4, DV360, TikTok, Shopify y Drive.
3. **Operación humana** — Claude Team / claude.ai (diseño de prompts, supervisión, decisión).

**Runtime:** un dispatcher genérico único despacha por el par `(client_id, agent_name)` recibido en el payload HTTP. Flujo E2E:

```
Cloud Scheduler (proyecto del cliente)
  → POST {client_id, agent_name}
  → carga config + secrets
  → construye system prompt (estático + dinámico)
  → loop Messages API (tool_use → tool_result … hasta end_turn)
  → parsea output
  → escribe a Drive 04_OUTPUTS/<client_id>/YYYY-MM-DD_<AREA>_<agent>.json
  → notifica si STATUS = ALERTA / ERROR
```

Una sola Cloud Function sirve a todos los clientes y agentes: **dar de alta un cliente nuevo NO implica un deploy.**

---

## Stack

- **Lenguaje:** Python 3.11+ · `functions_framework` (Cloud Functions **Gen2**, europe-west1; 1024 MB, timeout 300 s).
- **Modelo de IA:** Anthropic **Claude `claude-sonnet-4-6`**, vía **Messages API** con loop manual `tool_use`/`tool_result` (DEC_066 — *Managed Agents descartado*). SDK pin `anthropic>=0.103.0,<0.105.0`, `max_tokens=4096`.
- **GCP:** Cloud Functions Gen2 · Cloud Scheduler · Secret Manager · Cloud Logging (structured). Sin BigQuery ni Firestore en el runtime de agentes (estado S1 stateless; estado S2 previsto en Drive).
- **APIs / SDKs de plataforma:**
  - Meta Marketing — `facebook-business`
  - Google Ads — `google-ads`
  - GA4 — `google-analytics-data` (OAuth de admin-tech, no Service Account — DEC_067)
  - DV360 v4 — `googleapiclient` (Query API directa; **no** export a BigQuery — DEC_068)
  - Shopify Admin — GraphQL (read scopes)
  - TikTok Ads — `tiktok-business-api` (S2, pendiente)
  - Drive — `google-api-python-client`
  - Secret Manager — `google.cloud.secretmanager`

> Nota de stack: el sistema es deliberadamente **Claude-first**. Vertex AI / Gemini se descartó (los MCPs heredados sobre Vertex se consideraron stack incompatible; DEC_004, `META_arquitectura-github`).

---

## Estructura del repo

```
main.py                     # dispatcher HTTP (agent-executor)
tools/
  meta.py · google_ads.py · ga4.py · dv360.py · response.py
  definitions.py            # TOOL_DEFINITIONS_BY_AGENT — catálogo único (DEC_021)
prompt_builder.py           # system prompt estático + dinámico
system_prompts/
  <agent_snake>.md          # un prompt por agente
clients/
  <client_id>/config.json   # config por cliente (estructura + punteros)
  _template/config.json     # plantilla
naming_engine/
  compiled.json             # artefacto sincronizado desde llyc-naming-generator
scripts/
  setup_agent.py            # alta de agente por cliente
  dv360/                    # utilidades de escritura manual DV360
```

---

## Agentes

Disparados por Cloud Scheduler, sobre el mismo runtime:

| Agente | Cadencia | Nivel |
| :-- | :-- | :-- |
| performance-monitor | diario 08:00 | L1 (detectar/describir) |
| budget-pacer | 08:30 + 17:00 (guardrail mudo) | L1 |
| naming-utm-auditor | lunes 09:00 | determinista total, **sin LLM** (DEC_098) |
| weekly-digest | miércoles 10:00 | L2 (proponer con datos) |
| creative-fatigue-detector | — | S2, no operativo |
| trend-radar | — | S3, anticipatorio cross-cliente |

Añadir un agente = entrada en `tools/definitions.py` + fichero en `system_prompts/` + fila en el índice. **No toca el runtime.**

---

## Configuración (en capas)

- `clients/<id>/config.json` = **estructura y punteros**, nunca valores operativos.
- **Workbook operativo** por cliente (Google Sheet) = budget grid, KPIs, umbrales; se lee en runtime con validación + fallback + snapshot `reference_kpis_used`. Lo edita ops sin PR.
- Cadencia **solo** en Cloud Scheduler (prohibido `schedule` en config — DEC_087).
- Los JSON son artefactos generados por sync; el humano edita el Sheet, no el JSON a mano (DEC_075/078).

---

## Multi-tenant y entornos

Los "entornos" son **proyectos GCP por cliente**, no dev/staging/prod:

- `llyc-ai-first-core` — executor compartido + infra + secrets de agencia.
- `llyc-ai-<cliente>` — un proyecto por cliente (Scheduler + Secret Manager aislados). El executor recibe `client_id` por payload (DEC_030).

Onboarding N+1 (proceso en `RUNBOOK_onboarding-cliente`): config + proyecto GCP + secrets + Cloud Scheduler + espejo de config en Drive + INSTANCE de naming. **Cero código.**

---

## Seguridad y secretos

- Valores reales **solo** en Secret Manager: nunca en repo, Drive ni chat. En config solo nombres de variable. `.strip()` defensivo obligatorio al leer (DEC_067).
- Modelo híbrido (DEC_026): dato client-specific → Secret Manager del proyecto del cliente; capacidad de agencia (developer tokens, OAuth apps) → core. Acceso cross-project vía `secretmanager.secretAccessor`.
- Una `ANTHROPIC_API_KEY` dedicada por par `(client_id, agent_name)` (DEC_058), naming `anthropic-api-key-<agent_snake>-<client_id>`.
- **IAM read-only:** `llyc-agents-sa` sin permisos de escritura (DEC_086); la SA de escritura nunca se monta en runtime.
- Naming de secrets: `MAYÚSCULAS_SNAKE_CASE` (DEC_033); labels `platform/type/environment/(client)`.

## Contrato de tools

- Retorno `ok(platform, data)` / `error(platform, code, msg)`; `with_timeout()` (Meta/GAds/TikTok 30 s, GA4 20 s, Drive 15 s); hasta 2 reintentos con backoff; nunca se propaga excepción raw (DEC_056).
- Determinismo del ejecutor > LLM: todo campo computable lo fija el ejecutor (DEC_091).
- Estado dual: `execution_status` (OK/PARTIAL/ERROR) + `analysis_status` (ALERTA/NORMAL/N/A) (DEC_072). Logging JSON `tool_executed` / `tool_error` / `tool_exhausted` (DEC_070).

---

## CI/CD y gobierno del repo

- Org de producción **Apache-Media-Group**; branch protection en `main`, CODEOWNERS, squash/rebase-only, review de code-owner ≥1 (DEC_103).
- Ownership de PRs: código tool/agent → Max (primary) + Alberto (reviewer) · configs cliente → Alberto (primary) + Max (reviewer) · infra GCP → Sergio (primary) + Max (reviewer).
- Repo companion **llyc-naming-generator** (motor de naming/UTM → `naming_engine/compiled.json`, paridad por hash — DEC_120). Su app se despliega a Cloud Run vía Cloud Build `naming-generator-deploy`.
- **[VERIFICAR]** WIF / pipeline de CI del executor: no documentado en el KB — confirmar con Sergio antes de darlo por hecho en este README.

---

## Documentación (KB en Drive DM-AI-FIRST)

- `02_ARQUITECTURA/arquitectura-sistema.md` — fuente de verdad técnica.
- `02_ARQUITECTURA/entry-point-messages-api` — patrón Messages API + tool_use loop.
- `02_ARQUITECTURA/RUNBOOK_onboarding-cliente.md` — alta de cliente N+1.
- `00_META/decision-log.md` — guardarraíles (formato DEC_NNN, append-only).
- `00_META/META_github-runbook.md` — workflow de ramas/PRs y troubleshooting.

## Owner

Max (`admin-tech-llyc`) · Reviewer de código: Alberto González · Infra GCP: Sergio Alonso.
