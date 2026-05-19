---
name: new-client
description: Scaffold a new client directory from clients/_template/. Usage: /new-client <client-name>
disable-model-invocation: true
---

Scaffold a new client directory from the canonical template.

1. Copy everything under `clients/_template/` to `clients/$ARGUMENTS/`.
2. List the files created.
3. Tell the user which placeholders to fill in (look for TODO or placeholder values in the copied files).
