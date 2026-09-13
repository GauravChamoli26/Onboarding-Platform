# Onboarding Platform — Backend

Python service for the Employee Onboarding & Recruitment Platform.
Design documents live in `../docs/`. Start with `docs/00-documentation-index.md`.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12 or newer | `python --version` |
| Docker Desktop | current | Must be **running** — the test suite starts its own PostgreSQL container |
| Git | any | |

You do **not** need PostgreSQL installed locally. Docker provides it.

---

## Setup

### Windows (PowerShell)

`make` does not exist on Windows. Use `make.ps1`, which mirrors every Makefile target:

```powershell
cd backend
Copy-Item .env.example .env

.\make.ps1 venv                    # create the virtual environment
.\.venv\Scripts\Activate.ps1       # activate it — prompt gains a (.venv) prefix
.\make.ps1 install
.\make.ps1 up
.\make.ps1 test-isolation
```

Activate the virtual environment in **every new terminal** before working. If
the prompt does not start with `(.venv)`, packages will install to the system
Python and the application will not find them.

If PowerShell blocks the script, allow local scripts for your user once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Prefer not to use the script? Run the underlying commands directly:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
docker compose up -d
pytest -v -m integration tests/test_tenant_isolation.py
```

### macOS / Linux

```bash
cd backend
cp .env.example .env

make venv
source .venv/bin/activate
make install
make up
make test-isolation
```

Run `make help` or `.\make.ps1 help` to see every target.

---

## Verifying the setup

`test-isolation` should report **9 passing tests**. That is the proof that
row-level security is actually isolating tenants (ADR-002), and it is the check
that runs on every pull request from now on.

Worth doing once, so the team knows what a broken boundary looks like: comment
out the `FORCE ROW LEVEL SECURITY` line in `tests/conftest.py` and rerun.
`test_rls_is_forced_on_tenant_tables` will fail with a message naming exactly
what is missing. Then put it back.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `make : The term 'make' is not recognized` | Windows has no `make` | Use `.\make.ps1` |
| `error during connect` / `docker daemon` errors | Docker Desktop not started | Start it, wait for "Engine running" |
| `port 5432 already allocated` | Another PostgreSQL is running | Stop it, or change the host port in `docker-compose.yml` |
| `cannot be loaded because running scripts is disabled` | PowerShell execution policy | See the `Set-ExecutionPolicy` command above |
| Tests hang on first run | Docker is pulling the postgres image | Wait — subsequent runs are fast |
| `async def functions are not natively supported` | pytest run from the wrong directory | `cd backend` first — pyproject.toml is the config file, and pytest only finds it from there |
| `ModuleNotFoundError: platform_core` | Package not installed, or wrong environment active | Check the prompt shows `(.venv)`, then re-run `install` |
| `pip : The term 'pip' is not recognized` | Python not on PATH | See "Python not found" below |
| `python` opens the Microsoft Store | App Execution Alias stub, not a real install | Settings → Apps → Advanced app settings → App execution aliases → turn off the Python entries |
| Packages install but imports still fail | Installed outside the virtual environment | Activate `.venv` first, then reinstall |

---

## Python not found

If `pip` or `python` is not recognised, check what exists:

```powershell
Get-Command py, python, python3 -ErrorAction SilentlyContinue
```

**`py` is present** — use it. `py -m venv .venv`, then activate and continue
normally. The `py` launcher ships with the python.org installer and stays on
PATH even when `python` does not.

**Nothing is present** — install Python 3.12 or newer:

```powershell
winget install Python.Python.3.12
```

Close and reopen PowerShell afterwards so the new PATH is picked up. Installing
from python.org instead works equally well, but **tick "Add python.exe to PATH"**
on the first installer screen — it is unchecked by default, and that single box
is the cause of most "pip is not recognized" reports.

---

## Project layout

```
backend/
├── src/platform_core/     Shared kernel — used by every module
│   ├── config/            Settings, environment-backed and validated at boot
│   ├── db/                Engine, session handling, base model conventions
│   └── tenancy/           Tenant context driving row-level security
├── alembic/versions/      Migrations. RLS policies are hand-written here
├── tests/                 Isolation suite runs on every PR
└── scripts/               Database role bootstrap for local development
```

Phase 1 adds `auth/`, `events/`, `audit/`, `approvals/`, `notifications/`,
`sla/` to the shared kernel, then `src/modules/` for functional modules.

---

## A note on Windows

Production runs on Linux (ECS Fargate, ADR-012). Windows works fine for
development, but if you hit path or line-ending friction, **WSL2 is worth the
half hour** — Docker Desktop already uses it as a backend, and it removes a
class of "works on my machine" differences from the team.

Not required. Just the smoother road if Windows starts fighting you.
