"""Device inventory, loaded from YAML. Each device names a lab container and the commands to run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Device:
    name: str
    service: str  # docker compose service name
    sections: dict[str, str]  # section name -> shell command whose stdout is that section


def parse_inventory(data: Any) -> list[Device]:
    if not isinstance(data, dict) or not isinstance(data.get("devices"), list):
        raise ValueError("inventory must be a mapping with a 'devices' list")
    devices: list[Device] = []
    seen: set[str] = set()
    for entry in data["devices"]:
        if not isinstance(entry, dict):
            raise ValueError(f"device entry must be a mapping: {entry!r}")
        name = entry.get("name")
        service = entry.get("service")
        sections = entry.get("sections")
        if not isinstance(name, str) or not name:
            raise ValueError(f"device needs a name: {entry!r}")
        if not isinstance(service, str) or not service:
            raise ValueError(f"{name}: needs a service")
        if not isinstance(sections, dict) or not sections:
            raise ValueError(f"{name}: needs at least one section command")
        if any(not isinstance(v, str) for v in sections.values()):
            raise ValueError(f"{name}: section commands must be strings")
        if name in seen:
            raise ValueError(f"duplicate device name: {name}")
        seen.add(name)
        devices.append(Device(name=name, service=service, sections=dict(sections)))
    return devices


def load_inventory(path: Path) -> list[Device]:
    return parse_inventory(yaml.safe_load(path.read_text(encoding="utf-8")))
