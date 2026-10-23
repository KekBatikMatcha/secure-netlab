"""Static checks on the Suricata lab rules. The live engine check is in tests/integration/."""

from __future__ import annotations

import re
from pathlib import Path

import demo_traffic

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "lab" / "suricata" / "rules" / "lab.rules"
_SID = re.compile(r"sid:(\d+);")


def _rules() -> list[str]:
    return [
        line
        for line in RULES.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_every_rule_has_msg_sid_and_action() -> None:
    rules = _rules()
    assert rules, "no rules found"
    for rule in rules:
        assert rule.startswith("alert "), rule
        assert "msg:" in rule, rule
        assert _SID.search(rule), rule


def test_sids_are_unique_and_in_the_lab_range() -> None:
    sids = [int(_SID.search(r).group(1)) for r in _rules()]  # type: ignore[union-attr]
    assert len(sids) == len(set(sids)), "duplicate sid"
    assert all(1_000_001 <= sid <= 1_000_099 for sid in sids), sids


def test_industrial_rule_allow_list_matches_the_topology() -> None:
    # app-server (historian), eng-ws (engineering) and the monitor are the only permitted sources.
    rule = next(r for r in _rules() if "sid:1000001;" in r)
    assert "![10.10.20.10,10.10.30.10,10.10.30.20]" in rule


def test_every_expected_sid_in_the_demo_exists_as_a_rule() -> None:
    defined = {int(_SID.search(r).group(1)) for r in _rules()}  # type: ignore[union-attr]
    for name, scenario in demo_traffic.SCENARIOS.items():
        missing = scenario.expected_sids - defined
        assert not missing, f"{name} expects rules that do not exist: {missing}"


def test_rules_file_has_no_stray_non_rule_lines() -> None:
    for line in RULES.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        assert not stripped or stripped.startswith("#") or stripped.startswith("alert "), line
