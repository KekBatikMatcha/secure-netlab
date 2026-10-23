"""Basic repo checks that guard the hard rules (no real secrets, lab-only)."""

from pathlib import Path

import automation

ROOT = Path(__file__).resolve().parents[1]


def _parse_env(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines, ignoring blanks and comments."""
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def test_package_has_version() -> None:
    assert isinstance(automation.__version__, str)


def test_env_example_secrets_are_fake() -> None:
    # Every secret in .env.example must carry the FAKE- marker so real secrets cannot slip in.
    env = _parse_env(ROOT / ".env.example")
    secret_keys = [k for k in env if "PASSWORD" in k or "COMMUNITY" in k]
    assert secret_keys, "expected secret keys in .env.example"
    for key in secret_keys:
        assert env[key].startswith("FAKE-"), f"{key} must be a FAKE- placeholder"
