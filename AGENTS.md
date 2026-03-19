# Repository Guidelines

## Project Structure & Module Organization

- `app/`: main Python package and entrypoints.
  - `app/main.py`: launcher (GUI by default; can run monitor with a tunnel name arg).
  - `app/modern_gui.py`, `app/gui.py`: modern/classic Tkinter UIs.
  - `app/cloudflared_cli.py`: wrapper around `cloudflared` (login, tunnel CRUD, DNS routing, run/stop).
  - `app/tunnel_supervisor.py`: multi-tunnel supervisor CLI (start/stop/status/watch).
  - `app/tunnel_monitor_improved.py`: single-tunnel health monitor/reconnect script.
  - `app/components/`, `app/utils/`: reusable UI widgets, theme, logging, locks, process tracking.
- `config/`: runtime configuration at repo root (not `app/config/`), e.g. `config/tunnels.json`.
- `tunnels/`: per-tunnel configs/credentials (generated or user-managed).
- `logs/`: runtime logs and PID/lock files (generated).
- `cloudflared` / `cloudflared.exe`: bundled binaries (if present).

## Build, Test, and Development Commands

Run commands from the repo root to avoid import issues:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r app/requirements.txt
python -m app.main              # modern GUI
python -m app.main --classic    # classic GUI
python app/diagnose.py          # local diagnostics
python -m app.tunnel_supervisor list
python -m app.tunnel_supervisor watch --interval 30
```

## Coding Style & Naming Conventions

- Python 3.8+, 4-space indentation, PEP 8 conventions.
- Prefer explicit names (`tunnel_name`, `config_path`) and type hints where practical.
- Keep OS-specific logic isolated (Windows vs Linux/macOS).

## Testing Guidelines

- No full test suite is enforced; validate by running the GUI and critical flows (list/create/start/stop).
- If you add tests, prefer `pytest` and place them under `app/tests/` with `test_*.py` naming.
- Quick sanity checks: `python -m compileall app` and run any existing scripts like `app/test_bug4_fix.py`.

## Commit & Pull Request Guidelines

- Follow the existing commit style: `feat: ...`, `fix: ...`, `chore: ...` (Chinese descriptions are OK).
- PRs should include: clear description, reproduction/verification steps, and screenshots for UI changes.
- Keep changes focused; update relevant docs (`README.md`, `docs/TROUBLESHOOTING.md`) when behavior changes.

## Configuration & Security Tips

- Do not commit secrets: `cert.pem`, tunnel credentials JSON, or personal hostnames.
- Local runtime state lives in `config/app_config.json`, `config/tunnels.json`, and `logs/`; treat these as environment-specific.
