# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Tool executor y agentes para el sistema LLYC AI-First. GCP Cloud Function (HTTP trigger) que recibe solicitudes de cliente + tool, llama la plataforma correspondiente (Meta Ads, Google Ads, GA4, DV360, TikTok, Drive) usando Anthropic Managed Agents, y devuelve resultados estructurados.

## Local development

```bash
source .venv/bin/activate
gcloud auth application-default login   # required; no .env file exists
functions-framework --target=main --debug
```

All secrets are fetched from GCP Secret Manager at runtime — never use a local `.env` file.

## Architecture

| Path | Purpose |
|---|---|
| `main.py` | Cloud Function entrypoint (HTTP trigger) |
| `tools/` | One module per platform (meta.py, google_ads.py, ga4.py, …) |
| `clients/{name}/` | Per-client config and overrides |
| `clients/_template/` | Canonical scaffold — copy when adding a new client |

## Commands

```bash
ruff check .                                         # lint
ruff format .                                        # format
gcloud functions deploy <name> \
  --runtime python311 --trigger-http --source .      # deploy
```

## Python

- Version: 3.11+
- Virtualenv: `.venv/` — activate with `source .venv/bin/activate`
- Type hints on all public functions
