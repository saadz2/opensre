"""Unit tests for the Grafana Zabbix datasource query mixin."""

from __future__ import annotations

import time
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest

from integrations.grafana import zabbix as zabbix_module
from integrations.grafana.zabbix import ZabbixMixin

_NOW = int(time.time())
_ZABBIX_UID = "zbx-uid/1"


class DummyZabbixClient(ZabbixMixin):
    """Isolates the mixin from the network; routes each Zabbix API call by method."""

    def __init__(
        self, api_rows: dict[str, list[dict[str, Any]]] | None = None, is_configured: bool = True
    ) -> None:
        super().__init__()
        self.is_configured = is_configured
        self.account_id = "test_acc"
        self.instance_url = "https://grafana.example.com"
        self.zabbix_datasource_uid = _ZABBIX_UID
        self.api_rows = api_rows or {}
        self.api_calls: list[tuple[str, dict[str, Any]]] = []
        self._make_post_request = MagicMock(side_effect=self._route)

    def _route(self, _url: str, json_body: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        method = json_body["method"]
        self.api_calls.append((method, json_body["params"]))
        return {"result": self.api_rows.get(method, [])}

    def params_for(self, method: str) -> dict[str, Any]:
        return next(params for name, params in self.api_calls if name == method)


def _problem(event_id: str, *, clock: int, recovered_at: int = 0, trigger_id: str = "1") -> dict:
    return {
        "eventid": event_id,
        "objectid": trigger_id,
        "clock": str(clock),
        "r_eventid": "9999" if recovered_at else "0",
        "r_clock": str(recovered_at),
        "name": f"Problem {event_id}",
        "severity": "4",
        "acknowledged": "0",
        "suppressed": "0",
        "tags": [],
    }


def test_problems_resolve_host_filter_and_attach_trigger_hosts() -> None:
    client = DummyZabbixClient(
        {
            "host.get": [{"hostid": "10084"}],
            "problem.get": [_problem("1", clock=_NOW - 120)],
            "trigger.get": [{"triggerid": "1", "hosts": [{"hostid": "10084", "name": "web-01"}]}],
        }
    )

    result = client.query_zabbix_problems(host_filter="web-*", min_severity=3)

    assert result["success"] is True
    assert result["problems"][0]["hosts"] == ["web-01"]
    problem_params = client.params_for("problem.get")
    assert problem_params["hostids"] == ["10084"]
    assert problem_params["severities"] == [3, 4, 5]
    assert client.params_for("host.get")["searchWildcardsEnabled"] is True
    url = client._make_post_request.call_args_list[0].args[0]
    assert url == "https://grafana.example.com/api/datasources/uid/zbx-uid%2F1/resources/zabbix-api"


def test_problems_resolve_interface_ip_with_host_get() -> None:
    client = DummyZabbixClient(
        {
            "host.get": [
                {
                    "hostid": "10084",
                    "host": "web-01",
                    "name": "Web Server",
                    "interfaces": [{"ip": "172.31.45.206"}],
                }
            ],
            "problem.get": [],
        }
    )

    result = client.query_zabbix_problems(host_filter="172.31.45.206")

    assert result["success"] is True
    assert client.params_for("host.get")["selectInterfaces"] == ["ip"]
    assert client.params_for("problem.get")["hostids"] == ["10084"]


def test_problems_keep_old_active_ones_and_drop_stale_resolved_ones() -> None:
    old_active = _problem("1", clock=_NOW - 10 * 86400)
    recent_resolved = _problem("2", clock=_NOW - 600, recovered_at=_NOW - 300)
    stale_resolved = _problem("3", clock=_NOW - 5 * 86400, recovered_at=_NOW - 5 * 86400 + 60)
    client = DummyZabbixClient({"problem.get": [old_active, recent_resolved, stale_resolved]})

    result = client.query_zabbix_problems(time_range_minutes=60)

    assert [item["event_id"] for item in result["problems"]] == ["1", "2"]
    assert result["active_problems"] == 1
    assert result["total_problems"] == 2


def test_problems_unmatched_host_filter_returns_empty_without_querying_problems() -> None:
    client = DummyZabbixClient({"host.get": []})

    result = client.query_zabbix_problems(host_filter="ghost")

    assert result["success"] is True
    assert result["problems"] == []
    assert [name for name, _params in client.api_calls] == ["host.get"]


def test_problems_flag_truncation_when_the_fetch_hits_the_limit() -> None:
    rows = [_problem(str(index), clock=_NOW - 60) for index in range(3)]
    client = DummyZabbixClient({"problem.get": rows})

    assert client.query_zabbix_problems(limit=3)["truncated"] is True
    assert client.query_zabbix_problems(limit=10)["truncated"] is False


def test_zabbix_api_calls_are_limited_to_read_only_methods() -> None:
    client = DummyZabbixClient()

    with pytest.raises(ValueError, match="not allowed"):
        zabbix_module._call_zabbix_api(client, "event.acknowledge", {"eventids": "1"})  # type: ignore[arg-type]
    client._make_post_request.assert_not_called()


def test_problems_not_configured_exits_early() -> None:
    client = DummyZabbixClient(is_configured=False)

    result = client.query_zabbix_problems()

    assert result["success"] is False
    assert "not configured" in result["error"]
    client._make_post_request.assert_not_called()


def test_problems_http_failure_carries_the_vendor_reason() -> None:
    client = DummyZabbixClient()
    error = RuntimeError("boom")
    error.response = MagicMock(  # type: ignore[attr-defined]
        status_code=HTTPStatus.NOT_FOUND, text='{"message": "plugin not found"}'
    )
    client._make_post_request = MagicMock(side_effect=error)

    result = client.query_zabbix_problems()

    assert result["success"] is False
    assert "plugin not found" in result["error"]
    assert "Zabbix datasource" in result["error"]
    assert result["problems"] == []


_METRICS_RESPONSE = {
    "results": {
        "A": {
            "status": 200,
            "frames": [
                {
                    "schema": {
                        "refId": "A",
                        "fields": [
                            {"name": "Time", "type": "time"},
                            {
                                "name": "Value",
                                "type": "number",
                                "labels": {"host": "web-01"},
                                "config": {"displayNameFromDS": "web-01: CPU utilization"},
                            },
                        ],
                    },
                    "data": {"values": [[1_790_000_000_000, 1_790_000_060_000], [12.5, 97.5]]},
                }
            ],
        }
    }
}


def test_metrics_builds_zabbix_query_and_normalizes_frames() -> None:
    client = DummyZabbixClient()
    client._make_post_request = MagicMock(return_value=_METRICS_RESPONSE)

    result = client.query_zabbix_metrics("CPU utilization", host_filter="web-01")

    assert result["success"] is True
    assert result["total_series"] == 1
    assert result["metrics"][0]["max"] == 97.5
    assert result["account_id"] == "test_acc"
    url = client._make_post_request.call_args.args[0]
    body = client._make_post_request.call_args.kwargs["json_body"]
    assert url == "https://grafana.example.com/api/ds/query"
    query = body["queries"][0]
    assert query["datasource"] == {"uid": _ZABBIX_UID}
    assert query["queryType"] == "0"
    assert query["item"] == {"filter": "CPU utilization"}
    assert query["host"] == {"filter": "web-01"}
    assert query["group"] == {"filter": "/.*/"}
    assert int(body["to"]) - int(body["from"]) == 60 * 60 * 1000


def test_metrics_resolves_interface_ip_with_host_get() -> None:
    client = DummyZabbixClient()
    client._make_post_request = MagicMock(
        side_effect=[
            {
                "result": [
                    {
                        "hostid": "10084",
                        "host": "web-01",
                        "name": "Web Server",
                        "interfaces": [{"ip": "172.31.45.206"}],
                    }
                ]
            },
            _METRICS_RESPONSE,
        ]
    )

    result = client.query_zabbix_metrics("CPU utilization", host_filter="172.31.45.206")

    assert result["success"] is True
    calls = client._make_post_request.call_args_list
    host_request = calls[0].kwargs["json_body"]
    assert host_request["method"] == "host.get"
    assert host_request["params"]["selectInterfaces"] == ["ip"]
    query = calls[1].kwargs["json_body"]["queries"][0]
    assert query["host"]["filter"] == r"/^(web\-01|Web\ Server)$/"


def test_metrics_surfaces_a_query_error_reported_inside_a_200_response() -> None:
    client = DummyZabbixClient()
    client._make_post_request = MagicMock(
        return_value={"results": {"A": {"status": 400, "error": "Zabbix auth failed"}}}
    )

    result = client.query_zabbix_metrics("CPU utilization")

    assert result["success"] is False
    assert result["error"] == "Zabbix auth failed"
    assert result["metrics"] == []


def test_metrics_clamps_the_time_window() -> None:
    client = DummyZabbixClient()
    client._make_post_request = MagicMock(return_value=_METRICS_RESPONSE)

    client.query_zabbix_metrics("CPU utilization", time_range_minutes=10**9)

    body = client._make_post_request.call_args.kwargs["json_body"]
    assert int(body["to"]) - int(body["from"]) == 7 * 24 * 60 * 60 * 1000


def test_metrics_not_configured_exits_early() -> None:
    client = DummyZabbixClient(is_configured=False)

    result = client.query_zabbix_metrics("CPU utilization")

    assert result["success"] is False
    assert result["metrics"] == []
    client._make_post_request.assert_not_called()
