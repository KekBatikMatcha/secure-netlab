"""Versioned backup storage and approved baselines, both kept as plain text files.

Layout:
    backups/<device>/<UTC timestamp>.cfg   every config version that differed from the last one
    golden/<device>.cfg                    approved baseline (committed to git)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from automation.bundle import ConfigBundle

TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


class BackupStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _device_dir(self, device: str) -> Path:
        return self.root / device

    def versions(self, device: str) -> list[Path]:
        """All stored versions, oldest first (timestamps sort lexically)."""
        directory = self._device_dir(device)
        if not directory.is_dir():
            return []
        return sorted(directory.glob("*.cfg"))

    def latest_text(self, device: str) -> str | None:
        versions = self.versions(device)
        return versions[-1].read_text(encoding="utf-8") if versions else None

    def latest_bundle(self, device: str) -> ConfigBundle | None:
        text = self.latest_text(device)
        return ConfigBundle.from_text(text) if text is not None else None

    def save(self, device: str, bundle: ConfigBundle, when: datetime) -> Path | None:
        """Store a new version, or return None if it matches the newest stored version.

        Comparing normalized text means counter-only changes never create a version.
        """
        text = bundle.normalized().to_text()
        if self.latest_text(device) == text:
            return None
        directory = self._device_dir(device)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{when.strftime(TIMESTAMP_FORMAT)}.cfg"
        # Never overwrite history: add a suffix if two versions share a second.
        counter = 1
        while path.exists():
            path = directory / f"{when.strftime(TIMESTAMP_FORMAT)}-{counter}.cfg"
            counter += 1
        path.write_text(text, encoding="utf-8", newline="\n")
        return path


class BaselineStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, device: str) -> Path:
        return self.root / f"{device}.cfg"

    def load(self, device: str) -> ConfigBundle | None:
        path = self.path(device)
        if not path.is_file():
            return None
        return ConfigBundle.from_text(path.read_text(encoding="utf-8"))

    def accept(self, device: str, bundle: ConfigBundle) -> Path:
        """Make this bundle the approved baseline for the device."""
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path(device)
        path.write_text(bundle.normalized().to_text(), encoding="utf-8", newline="\n")
        return path
