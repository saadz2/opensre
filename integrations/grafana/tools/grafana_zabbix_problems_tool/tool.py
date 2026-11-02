"""``query_grafana_zabbix_problems`` — Zabbix problems through a Grafana Zabbix datasource."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

import integrations.grafana.tools._helpers as grafana_helpers
from core.tool import EvidenceType, SideEffectLevel
from core.tool_framework import tool
from core.tool_framework.utils import tool_unavailable
from integrations.grafana.tools.grafana_zabbix_problems_tool.results import (
    format_problems_summary,
    map_zabbix_problems,
)

_SOURCE = "grafana_zabbix"
_MAX_SEVERITY = 5
_MAX_RANGE_MINUTES = 7 * 24 * 60
_MAX_LIMIT = 200


class QueryGrafanaZabbixProblemsInput(BaseModel):
    host_filter: str = Field(
        default="",
        description="Host name to match; `*` is a wildcard. Empty matches every host.",
        examples=["web-01", "web-*"],
    )
    group_filter: str = Field(
        default="",
        description="Host group name to match; `*` is a wildcard. Empty matches every group.",
        examples=["Linux servers"],
    )
    min_severity: int = Field(
        default=0,
        ge=0,
        le=_MAX_SEVERITY,
        description=(
            "Lowest severity to return: 0 not classified, 1 information, 2 warning, "
            "3 average, 4 high, 5 disaster."
        ),
    )
    include_resolved: bool = Field(
        default=True,
        description="Also return problems that were resolved inside the time window.",
    )
    time_range_minutes: int = Field(
        default=60,
        ge=1,
        le=_MAX_RANGE_MINUTES,
        description="Window for resolved problems; still-active problems are always returned.",
    )
    limit: int = Field(
        default=50, ge=1, le=_MAX_LIMIT, description="Maximum problems to fetch, newest first."
    )


class QueryGrafanaZabbixProblemsOutput(BaseModel):
    source: str = Field(description="Evidence source label.")
    available: bool = Field(description="Whether the Zabbix query succeeded.")
    problems: list[dict[str, Any]] = Field(default_factory=list, description="Normalized problems.")
    total_problems: int = Field(default=0, description="Number of problems returned.")
    active_problems: int = Field(default=0, description="Problems that are not yet resolved.")
    truncated: bool = Field(default=False, description="True when the fetch hit the limit.")
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
    name="query_grafana_zabbix_problems",
    display_name="Grafana Zabbix Problems",
    source="grafana",
    evidence_mapper=map_zabbix_problems,
    description=(
        "List Zabbix problems (fired triggers) through Grafana's Zabbix datasource: "
        "active alerts plus recently resolved ones, with severity, start/recovery time, "
        "acknowledgement state, affected hosts and tags. Use when Grafana has a Zabbix datasource."
    ),
    use_cases=[
        "Finding which Zabbix triggers fired around an incident and on which hosts",
        "Checking whether a Zabbix problem is still active or already recovered",
        "Correlating Zabbix alert severity and timing with other evidence",
    ],
    source_id=_SOURCE,
    evidence_type=EvidenceType.EVENTS,
    side_effect_level=SideEffectLevel.READ_ONLY,
    examples=[
        "List high-severity Zabbix problems for hosts matching `web-*`.",
        "Check active Zabbix problems in the last 2 hours across all hosts.",
    ],
    anti_examples=[
        "Use query_grafana_zabbix_metrics for item history such as CPU or memory values.",
        "Use query_grafana_alert_rules for Grafana-managed alert rules, not Zabbix triggers.",
    ],
    input_model=QueryGrafanaZabbixProblemsInput,
    output_model=QueryGrafanaZabbixProblemsOutput,
    injected_params=grafana_helpers.ZABBIX_RUNTIME_PARAMS,
    is_available=grafana_helpers.zabbix_available,
    extract_params=_extract_params,
)
def query_grafana_zabbix_problems(
    host_filter: str = "",
    group_filter: str = "",
    min_severity: int = 0,
    include_resolved: bool = True,
    time_range_minutes: int = 60,
    limit: int = 50,
    grafana_endpoint: str | None = None,
    grafana_api_key: str | None = None,
    grafana_username: str = "",
    grafana_password: str = "",
    grafana_verify_ssl: bool = True,
    grafana_ca_bundle: str = "",
    **_kwargs: Any,
) -> dict:
    """List Zabbix problems through a Grafana Zabbix datasource."""
    client = grafana_helpers._resolve_grafana_client(
        grafana_endpoint,
        grafana_api_key,
        grafana_username,
        grafana_password,
        grafana_verify_ssl,
        grafana_ca_bundle,
    )
    if not client or not client.is_configured:
        return tool_unavailable(_SOURCE, "Grafana integration not configured", problems=[])
    if not client.zabbix_datasource_uid:
        return tool_unavailable(_SOURCE, "Zabbix datasource not found", problems=[])

    result = client.query_zabbix_problems(
        host_filter=host_filter,
        group_filter=group_filter,
        min_severity=min_severity,
        include_resolved=include_resolved,
        time_range_minutes=time_range_minutes,
        limit=limit,
    )
    if not result.get("success"):
        return tool_unavailable(_SOURCE, result.get("error", "Unknown error"), problems=[])

    problems = result.get("problems", [])
    total = result.get("total_problems", len(problems))
    active = result.get("active_problems", 0)
    return {
        "source": _SOURCE,
        "available": True,
        "problems": problems,
        "total_problems": total,
        "active_problems": active,
        "truncated": result.get("truncated", False),
        "account_id": client.account_id,
        "summary": format_problems_summary(total, active, host_filter=host_filter),
    }


__all__ = [
    "QueryGrafanaZabbixProblemsInput",
    "QueryGrafanaZabbixProblemsOutput",
    "query_grafana_zabbix_problems",
]
