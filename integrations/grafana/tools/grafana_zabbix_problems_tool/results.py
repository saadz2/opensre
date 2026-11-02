"""Evidence mapping and summaries for the Grafana Zabbix problems tool."""

from __future__ import annotations

from typing import Any

from core.domain.types.evidence import record_evidence_entry


def format_problems_summary(total: int, active: int, *, host_filter: str = "") -> str:
    """One-line user-facing summary for a Zabbix problems query result."""
    scope = f" for {host_filter}" if host_filter else ""
    return f"{total} Zabbix problem(s){scope}, {active} still active"


def map_zabbix_problems(
    evidence: dict[str, Any], output: dict[str, Any], _tool_input: dict[str, Any]
) -> None:
    """Store the problems and cite how many are still active."""
    problems = output.get("problems", [])
    evidence["grafana_zabbix_problems"] = problems
    if problems:
        record_evidence_entry(
            evidence,
            source="grafana_zabbix_problems",
            label="Grafana Zabbix Problems",
            summary=str(output.get("summary") or f"{len(problems)} problem(s)"),
        )
