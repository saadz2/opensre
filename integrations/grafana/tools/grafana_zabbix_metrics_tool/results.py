"""Evidence mapping and summaries for the Grafana Zabbix metrics tool."""

from __future__ import annotations

from typing import Any

from core.domain.types.evidence import record_evidence_entry


def format_metrics_summary(total_series: int, item_filter: str, *, host_filter: str = "") -> str:
    """One-line user-facing summary for a Zabbix metrics query result."""
    scope = f" for {host_filter}" if host_filter else ""
    return f"{total_series} series for `{item_filter}`{scope}"


def map_zabbix_metrics(
    evidence: dict[str, Any], output: dict[str, Any], tool_input: dict[str, Any]
) -> None:
    """Store the series and cite which item filter produced them."""
    metrics = output.get("metrics", [])
    item_filter = str(output.get("item_filter") or tool_input.get("item_filter") or "")
    results = evidence.setdefault("grafana_zabbix_metric_results", {})
    if isinstance(results, dict) and item_filter:
        results[item_filter] = output
    evidence["grafana_zabbix_metrics"] = metrics
    if metrics:
        record_evidence_entry(
            evidence,
            source="grafana_zabbix_metrics",
            label="Grafana Zabbix Metrics",
            summary=", ".join(
                part for part in (item_filter or None, f"{len(metrics)} series") if part
            ),
        )
