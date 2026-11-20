"""Embedded PostgreSQL for machines without Docker (dev + tests).

Usage:
    uv run python scripts/local_pg.py start    # idempotent; prints the two DATABASE URLs
    uv run python scripts/local_pg.py stop
    uv run python scripts/local_pg.py status

Uses the PostgreSQL 16 binaries shipped in the ``pgserver`` package, but starts the
server itself so that:
  * the port is fixed (``LOCAL_PG_PORT``, default 54329), so api/.env never goes stale;
  * the server log lives OUTSIDE the data directory. On Windows, a log file inside the
    data dir makes crash recovery fail ("could not open file ./log: sharing violation").

Creates roles ``vms`` (owner: migrations / system tasks) and ``vms_app`` (restricted,
RLS applies) and databases ``vms`` and ``vms_test``.
With Docker, use docker compose instead; infra/postgres/init.sql does the same there.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".pgdata"
LOG = ROOT / ".pgdata.log"
PORT = int(os.environ.get("LOCAL_PG_PORT", "54329"))
HOSTPORT = f"127.0.0.1:{PORT}"

SETUP = """
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vms') THEN
    CREATE ROLE vms LOGIN PASSWORD 'vms' CREATEDB;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vms_app') THEN
    CREATE ROLE vms_app LOGIN PASSWORD 'vms_app' NOSUPERUSER NOBYPASSRLS;
  END IF;
END $$;
"""


def _bin(name: str) -> str:
    import pgserver

    exe = Path(pgserver.__file__).parent / "pginstall" / "bin" / name
    return str(exe.with_suffix(".exe") if os.name == "nt" else exe)


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=check)


def _psql(sql: str, db: str = "postgres") -> str:
    r = _run(
        _bin("psql"),
        "-h",
        "127.0.0.1",
        "-p",
        str(PORT),
        "-U",
        "postgres",
        "-d",
        db,
        "-v",
        "ON_ERROR_STOP=1",
        "-tAc",
        sql,
    )
    return r.stdout.strip()


def _ready() -> bool:
    return _run(_bin("pg_isready"), "-h", "127.0.0.1", "-p", str(PORT), check=False).returncode == 0


def ensure() -> str:
    """Start (or reuse) the server, make sure roles/DBs exist; return host:port."""
    if not (DATA / "PG_VERSION").exists():
        DATA.mkdir(exist_ok=True)
        _run(_bin("initdb"), "-D", str(DATA), "-U", "postgres", "--auth=trust", "-E", "UTF8")
    stray = DATA / "log"
    if stray.is_file():  # left over from older pgserver-managed starts
        stray.rename(ROOT / ".pgdata.old.log")

    if not _ready():
        # No pipes: the server inherits pg_ctl's handles, and a captured pipe would
        # never reach EOF while the server runs. Output goes to LOG via -l anyway.
        subprocess.Popen(
            [
                _bin("pg_ctl"),
                "-D",
                str(DATA),
                "-l",
                str(LOG),
                "-o",
                f"-h 127.0.0.1 -p {PORT}",
                "start",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # Own process group and its own hidden console: Ctrl+C in, or closing, the
            # window that started it (e.g. start.bat's "VMS API") must not reach the
            # server, or it is killed mid-write and has to recover on the next start.
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.time() + 120  # crash recovery can take a while
        while not _ready():
            if time.time() > deadline:
                tail = LOG.read_text(errors="replace")[-2000:] if LOG.exists() else ""
                raise SystemExit(f"PostgreSQL did not start on {HOSTPORT}.\n{tail}")
            time.sleep(1)

    _psql(SETUP)
    for db in ("vms", "vms_test"):
        if _psql(f"SELECT 1 FROM pg_database WHERE datname = '{db}'") != "1":
            _psql(f"CREATE DATABASE {db} OWNER vms")
        _psql(f"GRANT CONNECT ON DATABASE {db} TO vms_app")
    return HOSTPORT


def start() -> None:
    hp = ensure()
    print(f"DATABASE_URL=postgresql+asyncpg://vms_app:vms_app@{hp}/vms")
    print(f"DATABASE_ADMIN_URL=postgresql+asyncpg://vms:vms@{hp}/vms")


def stop() -> None:
    r = _run(_bin("pg_ctl"), "-D", str(DATA), "-m", "fast", "stop", check=False)
    print(r.stdout.strip() or r.stderr.strip())


def status() -> None:
    print(f"{'running' if _ready() else 'not running'} on {HOSTPORT}")


if __name__ == "__main__":
    {"start": start, "stop": stop, "status": status}[
        sys.argv[1] if len(sys.argv) > 1 else "start"
    ]()
