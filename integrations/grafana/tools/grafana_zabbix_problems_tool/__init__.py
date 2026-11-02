"""Registry entrypoint for the Grafana Zabbix problems tool."""

from __future__ import annotations

from integrations.grafana.tools.grafana_zabbix_problems_tool.tool import (
    QueryGrafanaZabbixProblemsInput,
    QueryGrafanaZabbixProblemsOutput,
    query_grafana_zabbix_problems,
)

TOOL_MODULES = ("tool",)

__all__ = [
    "TOOL_MODULES",
    "QueryGrafanaZabbixProblemsInput",
    "QueryGrafanaZabbixProblemsOutput",
    "query_grafana_zabbix_problems",
]
