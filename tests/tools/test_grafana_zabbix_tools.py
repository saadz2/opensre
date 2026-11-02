"""Tests for the Grafana Zabbix tools (function-based, @tool decorated)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from integrations.grafana.tools import (
    query_grafana_zabbix_metrics,
    query_grafana_zabbix_problems,
)
from tests.tools.conftest import BaseToolContract

_RESOLVE_CLIENT = "integrations.grafana.tools._helpers._resolve_grafana_client"


class TestZabbixProblemsToolContract(BaseToolContract):
    def get_tool_under_test(self) -> Any:
        return query_grafana_zabbix_problems.__opensre_registered_tool__


class TestZabbixMetricsToolContract(BaseToolContract):
    def get_tool_under_test(self) -> Any:
        return query_grafana_zabbix_metrics.__opensre_registered_tool__


def _client(*, zabbix_uid: str | None = "zbx-uid", configured: bool = True) -> MagicMock:
    client = MagicMock()
    client.is_configured = configured
    client.zabbix_datasource_uid = zabbix_uid
    client.account_id = "acc-1"
    return client


@pytest.mark.parametrize("tool_fn", [query_grafana_zabbix_problems, query_grafana_zabbix_metrics])
def test_tools_need_grafana_credentials_and_skip_fixture_backends(tool_fn: Any) -> None:
    registered = tool_fn.__opensre_registered_tool__

    assert registered.is_available({"grafana": {"connection_verified": True}}) is True
    assert registered.is_available({"grafana": {}}) is False
    assert registered.is_available({}) is False
    assert (
        registered.is_available({"grafana": {"connection_verified": True, "_backend": object()}})
        is False
    )


@pytest.mark.parametrize("tool_fn", [query_grafana_zabbix_problems, query_grafana_zabbix_metrics])
def test_injected_grafana_credentials_stay_out_of_the_model_schema(tool_fn: Any) -> None:
    registered = tool_fn.__opensre_registered_tool__

    assert "grafana_api_key" in registered.injected_params
    assert "grafana_backend" not in registered.injected_params
    public_properties = set(registered.public_input_schema.get("properties", {}))
    assert {"grafana_endpoint", "grafana_api_key", "grafana_password"}.isdisjoint(public_properties)


def test_metrics_schema_requires_item_filter() -> None:
    registered = query_grafana_zabbix_metrics.__opensre_registered_tool__

    assert "item_filter" in registered.public_input_schema["required"]


@pytest.mark.parametrize("zabbix_uid", [None, ""])
def test_problems_reports_missing_zabbix_datasource(zabbix_uid: str | None) -> None:
    with patch(_RESOLVE_CLIENT, return_value=_client(zabbix_uid=zabbix_uid)):
        result = query_grafana_zabbix_problems(grafana_endpoint="http://grafana")

    assert result["available"] is False
    assert "Zabbix datasource not found" in result["error"]


def test_problems_reports_unconfigured_grafana() -> None:
    with patch(_RESOLVE_CLIENT, return_value=_client(configured=False)):
        result = query_grafana_zabbix_problems(grafana_endpoint="http://grafana")

    assert result["available"] is False
    assert "not configured" in result["error"]


def test_problems_happy_path_forwards_filters_and_summarizes() -> None:
    client = _client()
    client.query_zabbix_problems.return_value = {
        "success": True,
        "problems": [{"event_id": "1", "status": "problem"}],
        "total_problems": 1,
        "active_problems": 1,
        "truncated": False,
    }
    with patch(_RESOLVE_CLIENT, return_value=client):
        result = query_grafana_zabbix_problems(
            host_filter="web-*", min_severity=4, grafana_endpoint="http://grafana"
        )

    assert result["available"] is True
    assert result["active_problems"] == 1
    assert result["summary"] == "1 Zabbix problem(s) for web-*, 1 still active"
    kwargs = client.query_zabbix_problems.call_args.kwargs
    assert kwargs["host_filter"] == "web-*"
    assert kwargs["min_severity"] == 4


def test_problems_surfaces_client_failure_as_unavailable() -> None:
    client = _client()
    client.query_zabbix_problems.return_value = {"success": False, "error": "Zabbix query failed"}
    with patch(_RESOLVE_CLIENT, return_value=client):
        result = query_grafana_zabbix_problems(grafana_endpoint="http://grafana")

    assert result["available"] is False
    assert result["error"] == "Zabbix query failed"
    assert result["problems"] == []


def test_problems_evidence_mapper_records_an_entry_only_when_problems_exist() -> None:
    mapper = query_grafana_zabbix_problems.__opensre_registered_tool__.evidence_mapper
    evidence: dict[str, Any] = {}

    mapper(evidence, {"problems": [], "summary": "0 Zabbix problem(s), 0 still active"}, {})
    assert evidence["grafana_zabbix_problems"] == []
    assert "evidence_entries" not in evidence and not evidence.get("evidence")

    mapper(evidence, {"problems": [{"event_id": "1"}], "summary": "1 Zabbix problem(s)"}, {})
    assert evidence["grafana_zabbix_problems"] == [{"event_id": "1"}]


def test_metrics_rejects_a_blank_item_filter_without_querying() -> None:
    with patch(_RESOLVE_CLIENT) as resolve:
        result = query_grafana_zabbix_metrics(item_filter="  ", grafana_endpoint="http://grafana")

    assert result["available"] is False
    assert "item_filter" in result["error"]
    resolve.assert_not_called()


def test_metrics_reports_missing_zabbix_datasource() -> None:
    with patch(_RESOLVE_CLIENT, return_value=_client(zabbix_uid=None)):
        result = query_grafana_zabbix_metrics(
            item_filter="CPU utilization", grafana_endpoint="http://grafana"
        )

    assert result["available"] is False
    assert "Zabbix datasource not found" in result["error"]


def test_metrics_happy_path_forwards_filters_and_summarizes() -> None:
    client = _client()
    client.query_zabbix_metrics.return_value = {
        "success": True,
        "metrics": [{"name": "web-01: CPU utilization", "max": 97.5}],
        "total_series": 1,
        "truncated": False,
    }
    with patch(_RESOLVE_CLIENT, return_value=client):
        result = query_grafana_zabbix_metrics(
            item_filter="CPU utilization",
            host_filter="web-01",
            time_range_minutes=30,
            grafana_endpoint="http://grafana",
        )

    assert result["available"] is True
    assert result["total_series"] == 1
    assert result["summary"] == "1 series for `CPU utilization` for web-01"
    client.query_zabbix_metrics.assert_called_once_with(
        "CPU utilization", host_filter="web-01", group_filter="", time_range_minutes=30
    )


def test_metrics_surfaces_client_failure_as_unavailable() -> None:
    client = _client()
    client.query_zabbix_metrics.return_value = {"success": False, "error": "Zabbix auth failed"}
    with patch(_RESOLVE_CLIENT, return_value=client):
        result = query_grafana_zabbix_metrics(
            item_filter="CPU utilization", grafana_endpoint="http://grafana"
        )

    assert result["available"] is False
    assert result["error"] == "Zabbix auth failed"
    assert result["metrics"] == []


def test_metrics_evidence_mapper_stores_series_by_item_filter() -> None:
    mapper = query_grafana_zabbix_metrics.__opensre_registered_tool__.evidence_mapper
    evidence: dict[str, Any] = {}
    output = {"metrics": [{"name": "cpu"}], "item_filter": "CPU utilization"}

    mapper(evidence, output, {})

    assert evidence["grafana_zabbix_metrics"] == [{"name": "cpu"}]
    assert evidence["grafana_zabbix_metric_results"]["CPU utilization"] == output
