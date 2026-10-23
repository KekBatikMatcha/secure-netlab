"""Drift detection: compare a current config bundle with the approved baseline.

Two checks are implemented, matching the lab devices:
  * firewall (iptables-save format): chain policies and -A rules
  * listeners (netstat/ss output): which TCP ports are open

Severity:
  high   - a new allow rule or listener on a sensitive port (admin or Modbus), or a policy change
  medium - any other new/changed rule or listener
  low    - something stopped listening or was removed from a listener list
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from automation.bundle import ConfigBundle

# Ports where opening access is always high severity: remote administration (SSH, Telnet, web admin,
# NETCONF) and industrial control (Modbus/TCP on 502). An allow rule for the PLC from an unexpected
# segment is as serious as an admin port.
SENSITIVE_PORTS: frozenset[int] = frozenset({22, 23, 80, 443, 502, 830})

_DPORT = re.compile(r"--dport (\d+)")
_PORT = re.compile(r":(\d+)\b")  # first ":port" on a listener line, e.g. 0.0.0.0:22


@dataclass(frozen=True)
class Finding:
    kind: str
    severity: str  # "high" | "medium" | "low"
    detail: str


@dataclass(frozen=True)
class DriftReport:
    device: str
    findings: tuple[Finding, ...] = field(default_factory=tuple)

    @property
    def has_drift(self) -> bool:
        return bool(self.findings)

    def to_text(self) -> str:
        if not self.findings:
            return f"OK {self.device}: no drift"
        lines = [f"DRIFT {self.device}: {len(self.findings)} finding(s)"]
        lines += [f"  [{f.severity.upper()}] {f.kind}: {f.detail}" for f in self.findings]
        return "\n".join(lines)


def compare(device: str, baseline: ConfigBundle, current: ConfigBundle) -> DriftReport:
    base = baseline.normalized()
    cur = current.normalized()
    findings: list[Finding] = []

    for name in sorted(base.sections):
        if name not in cur.sections:
            findings.append(Finding("section-missing", "medium", f"{name} was not collected"))
    for name in sorted(cur.sections):
        if name not in base.sections:
            findings.append(Finding("section-added", "low", f"new section {name}"))

    # Only compare sections present on both sides; missing ones are reported above.
    if "firewall" in base.sections and "firewall" in cur.sections:
        findings += _compare_firewall(base.sections["firewall"], cur.sections["firewall"])
    if "listeners" in base.sections and "listeners" in cur.sections:
        findings += _compare_listeners(base.sections["listeners"], cur.sections["listeners"])

    return DriftReport(device=device, findings=tuple(findings))


def _policies_and_rules(text: str) -> tuple[dict[str, str], list[str]]:
    """Return chain policies (":FORWARD DROP") and rules ("-A FORWARD ...")."""
    policies: dict[str, str] = {}
    rules: list[str] = []
    for line in text.splitlines():
        if line.startswith(":"):
            parts = line[1:].split()
            if len(parts) >= 2:
                policies[parts[0]] = parts[1]
        elif line.startswith("-A "):
            rules.append(line)
    return policies, rules


def _rule_key(rule: str) -> tuple[str, str, str, str, str]:
    """Identity of a rule ignoring the port and conntrack match.

    Two rules with the same key but different text are treated as one rule that was changed.
    """
    tokens = rule.split()

    def option(flag: str) -> str:
        return tokens[tokens.index(flag) + 1] if flag in tokens else ""

    return (tokens[1], option("-s"), option("-d"), option("-p"), option("-j"))


def _rule_severity(rule: str) -> str:
    if " -j ACCEPT" in rule:
        match = _DPORT.search(rule)
        if match and int(match.group(1)) in SENSITIVE_PORTS:
            return "high"
    return "medium"


def _compare_firewall(base_text: str, cur_text: str) -> list[Finding]:
    base_policies, base_rules = _policies_and_rules(base_text)
    cur_policies, cur_rules = _policies_and_rules(cur_text)
    findings: list[Finding] = []

    for chain in sorted(set(base_policies) | set(cur_policies)):
        before, after = base_policies.get(chain, "-"), cur_policies.get(chain, "-")
        if before != after:
            findings.append(Finding("policy-changed", "high", f"{chain}: {before} -> {after}"))

    added = [rule for rule in cur_rules if rule not in base_rules]
    removed = [rule for rule in base_rules if rule not in cur_rules]
    paired_added: set[str] = set()
    paired_removed: set[str] = set()

    # A changed rule shows up as one removed + one added rule with the same key.
    # Only pair when the match is unambiguous (exactly one of each).
    for old in removed:
        key = _rule_key(old)
        same_removed = [r for r in removed if _rule_key(r) == key]
        same_added = [a for a in added if _rule_key(a) == key]
        if len(same_removed) == 1 and len(same_added) == 1:
            new = same_added[0]
            findings.append(
                Finding("firewall-rule-changed", _rule_severity(new), f"{old}  =>  {new}")
            )
            paired_added.add(new)
            paired_removed.add(old)

    for rule in added:
        if rule not in paired_added:
            findings.append(
                Finding("firewall-rule-added", _rule_severity(rule), rule)
            )
    for rule in removed:
        if rule not in paired_removed:
            findings.append(Finding("firewall-rule-removed", "medium", rule))
    return findings


def _listening_ports(text: str) -> set[int]:
    ports: set[int] = set()
    for line in text.splitlines():
        if "LISTEN" in line:
            match = _PORT.search(line)
            if match:
                ports.add(int(match.group(1)))
    return ports


def _compare_listeners(base_text: str, cur_text: str) -> list[Finding]:
    before = _listening_ports(base_text)
    after = _listening_ports(cur_text)
    findings: list[Finding] = []
    for port in sorted(after - before):
        if port in SENSITIVE_PORTS:
            findings.append(
                Finding("listener-added", "high", f"tcp/{port} now listening (sensitive port)")
            )
        else:
            findings.append(Finding("listener-added", "medium", f"tcp/{port} now listening"))
    for port in sorted(before - after):
        findings.append(Finding("listener-removed", "low", f"tcp/{port} no longer listening"))
    return findings
