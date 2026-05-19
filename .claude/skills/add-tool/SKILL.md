---
name: add-tool
description: Scaffold a new platform tool module in tools/. Usage: /add-tool <platform-name>
---

Scaffold a new tool module for the given platform.

1. Create `tools/$ARGUMENTS.py` with:
   - A module-level docstring naming the platform
   - A `run(client_config: dict, params: dict) -> dict` entry function
   - TODO comments marking where the actual API calls go
2. If `main.py` exists, add the import and route this tool there.
3. Remind the user to add the platform SDK to `requirements.txt` if it isn't already listed.
