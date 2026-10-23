# Secure Network Automation & Monitoring Lab

A fully containerised, reproducible lab on localhost. It covers config automation with drift detection, monitoring and alerting, intrusion detection, and a documented threat model.

**Scope rules:** simulated devices only, no real networks, no exploit code. Detection test traffic is generated inside the lab.

## Status

- [x] Phase 0: bootstrap (tooling, CI, hygiene tests)
- [ ] Phase 1: segmented Docker Compose lab
- [ ] Phase 2: config backup and drift detection
- [ ] Phase 3: monitoring and alerting
- [ ] Phase 4: intrusion detection (Suricata)
- [ ] Phase 5: threat model and polish

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install ruff pytest
ruff check .
pytest
```
