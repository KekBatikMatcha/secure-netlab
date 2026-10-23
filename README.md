# Secure Network Automation & Monitoring Lab

A fully containerised, reproducible lab on localhost. It covers config automation with drift detection, monitoring and alerting, intrusion detection, and a documented threat model.

**Scope rules:** simulated devices only, no real networks, no exploit code. Detection test traffic is generated inside the lab.

## Status

- [x] Phase 0: bootstrap (tooling, CI, hygiene tests)
- [x] Phase 1: segmented Docker Compose lab (see [docs/topology.md](docs/topology.md))
- [x] Phase 2: config backup and drift detection (see [docs/config-drift.md](docs/config-drift.md))
- [ ] Phase 3: monitoring and alerting
- [x] Phase 4: intrusion detection, Suricata rules and eve.json alerts in Grafana (see [docs/ids.md](docs/ids.md))
- [ ] Phase 5: threat model and polish

## Quick start

Requires Docker (Compose v2) and Python 3.11+.

```bash
make up           # build and start the lab on internal networks (no host ports)
make integration  # segmentation + Modbus checks against the running lab
make down         # stop the lab and remove its volumes
make test         # lint + unit tests + integration tests
make check        # back up all devices, store changes, report drift (exit 1 on drift)
make demo-traffic # harmless detection-test traffic; IDS alerts appear in Grafana (docs/ids.md)
```

Config backup and drift: `python -m automation baseline router` accepts the current config as the
baseline, `python -m automation run --every 300` repeats the check. See
[docs/config-drift.md](docs/config-drift.md).

Windows without `make`: run the same commands directly from PowerShell:

```powershell
docker compose -f compose/docker-compose.yml up -d --build --wait
.\.venv\Scripts\python.exe -m pytest -m "not integration"
.\.venv\Scripts\python.exe -m pytest -m integration
docker compose -f compose/docker-compose.yml down -v
```

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -m "not integration"
```
