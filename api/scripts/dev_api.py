"""Local dev entry point: make sure the embedded Postgres is running, then start the API.

uv run python scripts/dev_api.py        (used by .claude/launch.json "api")
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from local_pg import ensure  # noqa: E402

if __name__ == "__main__":
    print(f"PostgreSQL ready on {ensure()}", flush=True)
    import uvicorn

    root = Path(__file__).resolve().parents[1]
    os.chdir(root)  # so api/.env is found
    uvicorn.run(
        "app.main:app",
        app_dir=str(root),  # put api/ on sys.path, including in the reloader's child process
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=[str(root / "app")],
        # Live streams (SSE) stay open for minutes; don't let them hold up a reload.
        # Clients reconnect on their own.
        timeout_graceful_shutdown=3,
    )
