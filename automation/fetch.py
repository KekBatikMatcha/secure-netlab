"""Fetchers collect a device's config bundle.

DockerExecFetcher runs each section command inside the device's lab container with
`docker compose exec`. A future SSH fetcher (Netmiko) would implement the same fetch() method.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from automation.bundle import ConfigBundle
from automation.inventory import Device

Runner = Callable[..., subprocess.CompletedProcess[str]]


class FetchError(RuntimeError):
    """A device could not be fully collected. No partial bundle is returned or stored."""


class Fetcher(Protocol):
    def fetch(self, device: Device) -> ConfigBundle: ...


class DockerExecFetcher:
    def __init__(
        self,
        compose_file: Path,
        runner: Runner = subprocess.run,
        timeout: float = 60,
    ) -> None:
        self.compose_file = compose_file
        self.runner = runner
        self.timeout = timeout

    def _argv(self, device: Device, command: str) -> list[str]:
        # Pass the command as one argv element to `sh -c`, so no shell quoting is needed here.
        return [
            "docker",
            "compose",
            "-f",
            str(self.compose_file),
            "exec",
            "-T",
            device.service,
            "sh",
            "-c",
            command,
        ]

    def fetch(self, device: Device) -> ConfigBundle:
        sections: dict[str, str] = {}
        for name, command in device.sections.items():
            proc = self.runner(
                self._argv(device, command),
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
            if proc.returncode != 0:
                detail = (proc.stderr or "").strip()
                raise FetchError(f"{device.name}/{name}: exit {proc.returncode}: {detail}")
            sections[name] = proc.stdout
        return ConfigBundle(sections)
