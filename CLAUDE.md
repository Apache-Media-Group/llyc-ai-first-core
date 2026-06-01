# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Tool executor y agentes para el sistema LLYC AI-First. GCP Cloud Function (HTTP trigger) que recibe solicitudes de cliente + tool, llama la plataforma correspondiente (Meta Ads, Google Ads, GA4, DV360, TikTok, Shopify) usando Anthropic Messages API + tool_use, y devuelve resultados estructurados.

**Frontera del sistema:** el sistema **detecta y analiza, no decide**. Acceso read-only a todas las plataformas. Cualquier acción operativa (cambiar puja, pausar campaña, modificar presupuesto, lanzar creatividad) la toma el equipo humano fuera del sistema. No añadir tools de escritura sin decisión explícita en `decision-log.md`.

## Architecture

| Path | Purpose |
|---|---|
| `main.py` | Cloud Function entrypoint (HTTP trigger). Routes incoming tool calls del agente al `tools/<source>.py` correspondiente. |
| `tools/` | One module per data source. **Paid media (read-only):** `meta.py`, `google_ads.py`, `ga4.py`, `dv360.py`, `tiktok.py`. **Revenue ground truth (read-only):** `shopify.py`. Each exposes `run(client_config: dict, params: dict) -> dict`. |
| `clients/{name}/` | Per-client config and overrides. Each contains `config.json` with platform IDs, account IDs, Shopify store handle, naming patterns, KPIs. |
| `clients/_template/` | Canonical scaffold — copy via `/new-client` skill when onboarding. Contains `PENDIENTE` sentinels for required fields. |
| `system_prompts/<agent_key>.md` | Static system prompt por agente. Snake_case en el fichero, kebab-case en `agent_id` externo — mapping en `main.py:506`. |
| `scripts/` | Utilidades de operación: `bootstrap_agent.py` para inicialización del agente desde prompt estático + config cliente. Post-DEC_065 queda como no-op runtime (solo trazabilidad histórica). |

### Repo de código vs knowledge base

Este repo contiene **código** del agent-executor. La documentación arquitectónica del proyecto (`00_META/`, `02_ARQUITECTURA/`, decision-log, etc.) vive en el knowledge base de Drive — **no aquí**. Cualquier referencia tipo `02_ARQUITECTURA/...` en conversaciones se resuelve en Drive, no en este repo.

Mapping de naming: `agent_id` (kebab-case, ej. `performance-monitor`) → fichero del prompt (snake_case, ej. `performance_monitor.md`). El mapping se aplica en `main.py:506`.

### Anthropic API integration (post-DEC_065)

- **API pattern:** Messages API (`client.messages.create()`) con loop manual `tool_use` → tool handler → `tool_result` hasta `stop_reason == "end_turn"`. Implementación en `run_agent()` (`main.py`).
- **SDK constraint:** `anthropic>=0.103.0,<0.105.0` en `requirements.txt`. Versiones anteriores rompen tool_use estable; 0.105+ no validado E2E. NO quitar el upper bound sin re-validación.
- **Managed Agents — NOT used (DEC_065):** la beta `managed-agents-2026-04-01` fue descartada el 27/05/2026. Está diseñada para agentes con toolset Claude Code (sandbox + filesystem/shell), no para agentes que consultan APIs externas custom (Meta, Google Ads, GA4). El `agent_id` en `clients/<name>/config.json` queda por trazabilidad histórica, sin uso en runtime. Sprint 2+ puede reincorporar Managed Agents por agente concreto como excepción, no como patrón general.
- **Models:** `claude-sonnet-4-6` for routine agent runs. Reserve `claude-opus-4-7` for weekly consolidation or high-stakes analysis.
- **System prompt structure:** static part loaded from `system_prompts/<agent_key>.md`; dynamic part (cliente, fecha, plataformas activas, umbrales) injected from `clients/<name>/config.json` at runtime. Mapping `agent_id` (kebab) → fichero (snake) en `main.py:506`.
- **GCP projects:** one per client (`llyc-ai-vidal-vidal`, `llyc-ai-lcdc`). Core project: `llyc-ai-first-core` (shared infrastructure only).

### Revenue ground truth: Shopify

Shopify is the **single source of truth for ecomm revenue**, not GA4. Observed discrepancies between GA4-reported revenue and Shopify-actual revenue have exceeded 2x in pilot data. Agents that compute ROAS, CPA, or conversion metrics must use Shopify revenue as the reference, with GA4 and platform-reported figures shown as deltas (signals of attribution issues, not as truth).

For multi-channel clients (e.g., La Casa de las Carcasas, Sprint 2+), Shopify covers ecomm only; in-store retail revenue lives in a separate retail-tickets source — integration scope and SDK TBD, out of Sprint 1 unless added to `decision-log.md`.

## Team ownership

- **Max:** development del tool executor (Python), arquitectura y scope.
- **Alberto:** configs cliente en `clients/<name>/`, reviewer de PRs de tool/agent code.
- **Sergio:** infra GCP — Cloud Functions, Secret Manager, IAM, Cloud Scheduler.

Operativa de PRs: tool/agent code → Max primary, Alberto reviewer; configs cliente → Alberto primary, Max reviewer; infra GCP → Sergio primary, Max reviewer.

Detalle completo en `META_sintesis-proyecto.md` del knowledge base.

## Local development

```bash
source .venv/bin/activate
gcloud auth application-default login   # required; no .env file exists
functions-framework --target=main --debug
```

All secrets are fetched from GCP Secret Manager at runtime — never use a local `.env` file.

## Commands

```bash
ruff check .                                                       # lint
ruff format .                                                      # format
gcloud functions deploy <name> \
  --runtime python311 --trigger-http --source . \
  --memory=1024MB --timeout=540s \
  --service-account=llyc-agents-sa@llyc-ai-first-core.iam.gserviceaccount.com
```

The `--memory=1024MB --timeout=540s --service-account=...` flags are mandatory, not optional. Defaults (256MB / 60s / App Engine default SA) break the agent and were the technical debt resolved in Sprint 0.

## Logging

Use `google.cloud.logging.Client().setup_logging()` at process start. Do NOT use `logging.basicConfig()` — it does not propagate correctly in Cloud Functions Gen 2 and produces unstructured logs that lose context silently.

Read structured logs with field extraction (avoid column-based formats — they silently truncate JSON fields):

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="agent-executor"' \
  --format="value(jsonPayload.event,jsonPayload.client_id,jsonPayload.agent,timestamp)"
```

> **Gen 2 gotcha**: las Cloud Functions Gen 2 corren como Cloud Run services por debajo. Los runtime logs viven bajo `resource.type=cloud_run_revision`, NO bajo `resource.type=cloud_function` (este último solo devuelve audit logs de deploys/updates, no la actividad del código).

## Cloud Scheduler

Scheduler jobs live in per-client GCP projects (`llyc-ai-<client>`), not in `llyc-ai-first-core`. The core project is for shared infrastructure; per-client projects own per-client schedules, secrets, and quotas. This was the technical debt resolved in Sprint 0.

## Config validation

Every `clients/<name>/config.json` must pass `INVALID_VALUES` validation before any deploy or agent run:

```python
INVALID_VALUES = {"PENDIENTE", "", None, 0, 0.0}
```

If any required field contains an `INVALID_VALUES` value, fail loudly with the field name. Never deploy or call APIs with a `PENDIENTE` config — it produces silently wrong outputs and corrupts trust in the agent.

## Naming convention

Two rules, no exceptions:

- Within a block: words joined with `-`.
- Between blocks: separator is `_`.

For living documents (configs, contexts, guides, system prompts — anything edited in place): `ÁREA_descripción.md`. No date in the filename. The current version is always the file; history lives in `CHANGELOG.md` per folder or in git.

For immutable outputs (snapshots, agent outputs, frozen reports): `YYYY-MM-DD_ÁREA_descripción.ext`. The date freezes the snapshot.

Areas: `PAID`, `DATA`, `META`, `CREATIVIDAD`.

Rationale: dating a living document forces a rename on every update, which breaks linked URLs in the Claude Team knowledge base.

## Python

- Version: 3.11+
- Virtualenv: `.venv/` — activate with `source .venv/bin/activate`
- Type hints on all public functions
