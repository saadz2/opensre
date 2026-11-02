"""``query_grafana_zabbix_metrics`` — Zabbix item history through a Grafana Zabbix datasource."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

import integrations.grafana.tools._helpers as grafana_helpers
from core.tool import EvidenceType, SideEffectLevel
from core.tool_framework import tool
from core.tool_framework.utils import tool_unavailable
from integrations.grafana.tools.grafana_zabbix_metrics_tool.results import (
    format_metrics_summary,
    map_zabbix_metrics,
)

_SOURCE = "grafana_zabbix"
_MAX_RANGE_MINUTES = 7 * 24 * 60


class QueryGrafanaZabbixMetricsInput(BaseModel):
    item_filter: str = Field(
        description=(
            "Zabbix item name to read, or a `/regex/` to match several items. "
            "Required; an empty value would match every item."
        ),
        examples=["CPU utilization", "/Memory.*/"],
    )
    host_filter: str = Field(
        default="",
        description=(
            "Zabbix host name, interface IP address, or `/regex/`. Empty matches every host."
        ),
        examples=["web-01", "/web-.*/"],
    )
    group_filter: str = Field(
        default="",
        description="Host group name or `/regex/`. Empty matches every group.",
        examples=["Linux servers"],
    )
    time_range_minutes: int = Field(
        default=60,
        ge=1,
        le=_MAX_RANGE_MINUTES,
        description="Lookback window in minutes.",
    )


class QueryGrafanaZabbixMetricsOutput(BaseModel):
    source: str = Field(description="Evidence source label.")
    available: bool = Field(description="Whether the Zabbix query succeeded.")
    item_filter: str = Field(default="", description="Item filter that was executed.")
    total_series: int = Field(default=0, description="Number of series the query matched.")
    truncated: bool = Field(default=False, description="True when series were capped.")
    metrics: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Per-item series with min/max/avg/last stats and sampled points.",
    )
    error: str | None = Field(default=None, description="Error details when the query fails.")
    account_id: str | None = Field(default=None, description="Grafana account id when available.")
    summary: str | None = Field(default=None, description="One-line summary of the result.")


def _extract_params(sources: dict[str, dict]) -> dict[str, Any]:
    grafana = grafana_helpers._grafana_source(sources)
    return {
        "time_range_minutes": grafana.get("time_range_minutes", 60),
        **grafana_helpers._grafana_creds(grafana),
    }


@tool(
    name="query_grafana_zabbix_metrics",
    display_name="Grafana Zabbix Metrics",
    source="grafana",
    evidence_mapper=map_zabbix_metrics,
    description=(
        "Read Zabbix item history (CPU, memory, disk, network, custom items) through "
        "Grafana's Zabbix datasource. Use for Zabbix items, not PromQL. Requires an "
        "item_filter; narrow with a Zabbix host name, interface IP address, or group_filter. "
        "Returns per-item min/max/avg/last stats and sampled points."
    ),
    use_cases=[
        "Checking CPU, memory, disk or network trends on a host Zabbix monitors",
        "Checking Zabbix CPU or memory items for a host identified by interface IP",
        "Confirming a resource spike around the time a Zabbix problem fired",
        "Comparing an item across several hosts with a regex host filter",
    ],
    requires=["item_filter"],
    source_id=_SOURCE,
    evidence_type=EvidenceType.METRICS,
    side_effect_level=SideEffectLevel.READ_ONLY,
    examples=[
        "Query `CPU utilization` on host `web-01` for the last 30 minutes.",
        "Query Zabbix CPU and memory items for host IP `172.31.45.206`.",
        "Query `/Free disk space.*/` across hosts matching `/db-.*/`.",
    ],
    anti_examples=[
        "Use query_grafana_zabbix_problems to list fired triggers, not item history.",
        "Use query_grafana_metrics for Prometheus/Mimir PromQL, not Zabbix items.",
    ],
    input_model=QueryGrafanaZabbixMetricsInput,
    output_model=QueryGrafanaZabbixMetricsOutput,
    injected_params=grafana_helpers.ZABBIX_RUNTIME_PARAMS,
    is_available=grafana_helpers.zabbix_available,
    extract_params=_extract_params,
)
def query_grafana_zabbix_metrics(
    item_filter: str,
    host_filter: str = "",
    group_filter: str = "",
    time_range_minutes: int = 60,
    grafana_endpoint: str | None = None,
    grafana_api_key: str | None = None,
    grafana_username: str = "",
    grafana_password: str = "",
    grafana_verify_ssl: bool = True,
    grafana_ca_bundle: str = "",
    **_kwargs: Any,
) -> dict:
    """Read Zabbix item history through a Grafana Zabbix datasource."""
    if not item_filter.strip():
        return tool_unavailable(_SOURCE, "item_filter is required", metrics=[])

    client = grafana_helpers._resolve_grafana_client(
        grafana_endpoint,
        grafana_api_key,
        grafana_username,
        grafana_password,
        grafana_verify_ssl,
        grafana_ca_bundle,
    )
    if not client or not client.is_configured:
        return tool_unavailable(_SOURCE, "Grafana integration not configured", metrics=[])
    if not client.zabbix_datasource_uid:
        return tool_unavailable(_SOURCE, "Zabbix datasource not found", metrics=[])

    result = client.query_zabbix_metrics(
        item_filter,
        host_filter=host_filter,
        group_filter=group_filter,
        time_range_minutes=time_range_minutes,
    )
    if not result.get("success"):
        return tool_unavailable(_SOURCE, result.get("error", "Unknown error"), metrics=[])

    metrics = result.get("metrics", [])
    total_series = result.get("total_series", len(metrics))
    return {
        "source": _SOURCE,
        "available": True,
        "metrics": metrics,
        "total_series": total_series,
        "truncated": result.get("truncated", False),
        "item_filter": item_filter,
        "account_id": client.account_id,
        "summary": format_metrics_summary(total_series, item_filter, host_filter=host_filter),
    }


__all__ = [
    "QueryGrafanaZabbixMetricsInput",
    "QueryGrafanaZabbixMetricsOutput",
    "query_grafana_zabbix_metrics",
]
