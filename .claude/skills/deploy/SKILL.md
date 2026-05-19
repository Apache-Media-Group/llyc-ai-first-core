---
name: deploy
description: Deploy a named Cloud Function to GCP. Usage: /deploy <function-name>
disable-model-invocation: true
---

Deploy the specified Cloud Function to GCP.

1. Run: `gcloud functions deploy $ARGUMENTS --runtime python311 --trigger-http --source .`
2. Report the deployed URL shown in the output.
3. If it fails, show the error verbatim and suggest likely fixes (missing IAM role, wrong runtime, missing dependency).
