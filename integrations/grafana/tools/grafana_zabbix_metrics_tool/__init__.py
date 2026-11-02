"""Registry entrypoint for the Grafana Zabbix metrics tool."""

from __future__ import annotations

from integrations.grafana.tools.grafana_zabbix_metrics_tool.tool import (
    QueryGrafanaZabbixMetricsInput,
    QueryGrafanaZabbixMetricsOutput,
    query_grafana_zabbix_metrics,
)

TOOL_MODULES = ("tool",)

__all__ = [
    "TOOL_MODULES",
    "QueryGrafanaZabbixMetricsInput",
    "QueryGrafanaZabbixMetricsOutput",
    "query_grafana_zabbix_metrics",
]
