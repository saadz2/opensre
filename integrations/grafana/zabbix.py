"""Zabbix query mixin for the Grafana client (Zabbix datasource plugin)."""

from __future__ import annotations

import time
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from integrations.grafana.zabbix_parsing import (
    error_detail,
    extract_query_error,
    frames_to_series,
    is_resolved,
    last_activity_seconds,
    normalize_problem,
)

if TYPE_CHECKING:
    from integrations.grafana.base import GrafanaClientBase

#: Zabbix API methods this client may call through the datasource resource
#: endpoint — read-only lookups only; the plugin also exposes mutating methods.
_READ_ONLY_API_METHODS = frozenset({"problem.get", "trigger.get", "host.get", "hostgroup.get"})

_RESOURCE_PATH = "/api/datasources/uid/{uid}/resources/zabbix-api"
_QUERY_PATH = "/api/ds/query"
_REQUEST_TIMEOUT_SECONDS = 30
_METRICS_QUERY_TYPE = "0"
_REF_ID = "A"
#: The plugin treats ``/.../`` as a regular expression; this matches every name.
_MATCH_ALL = "/.*/"
_MAX_RANGE_MINUTES = 7 * 24 * 60
_MAX_PROBLEM_LIMIT = 200
_MAX_LOOKUP_IDS = 100
_MAX_SEVERITY = 5
_MAX_DATA_POINTS = 300
_MIN_INTERVAL_MS = 1000
_MAX_SERIES = 25
_MAX_POINTS_PER_SERIES = 30


def _describe_failure(status: int, body: str) -> str:
    """Error message for a failed Zabbix response, carrying the vendor's reason."""
    message = f"Zabbix query failed: {status}"
    detail = error_detail(body)
    if detail:
        message = f"{message}: {detail}"
    if status == HTTPStatus.NOT_FOUND:
        message += (
            " (the Grafana Zabbix datasource was not found: the configured Zabbix "
            "datasource UID likely does not exist or is not the Zabbix plugin)"
        )
    elif status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
        message += " (the Grafana credentials cannot access this Zabbix datasource)"
    return message


def _failure(exc: Exception, **empty: Any) -> dict[str, Any]:
    """Structured failure result, carrying the HTTP reason when the error has a response."""
    error_msg = str(exc)
    response_text = ""
    response = getattr(exc, "response", None)
    if response is not None:
        response_text = response.text[:300]
        error_msg = _describe_failure(response.status_code, response.text)
    return {"success": False, "error": error_msg, "response": response_text, **empty}


def _call_zabbix_api(client: GrafanaClientBase, method: str, params: dict[str, Any]) -> list[Any]:
    """Run one read-only Zabbix API method through the datasource resource endpoint."""
    if method not in _READ_ONLY_API_METHODS:
        raise ValueError(f"Zabbix API method {method!r} is not allowed")
    url = client.instance_url + _RESOURCE_PATH.format(
        uid=quote(client.zabbix_datasource_uid, safe="")
    )
    data = client._make_post_request(
        url,
        json_body={"method": method, "params": params},
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    result = data.get("result", [])
    return result if isinstance(result, list) else []


def _lookup_ids(
    client: GrafanaClientBase, method: str, id_field: str, search: dict[str, list[str]]
) -> list[str]:
    """IDs of hosts or host groups whose names contain the filter (``*`` wildcards allowed)."""
    params: dict[str, Any] = {
        "output": [id_field],
        "search": search,
        "searchByAny": True,
        "searchWildcardsEnabled": True,
        "limit": _MAX_LOOKUP_IDS,
    }
    rows = _call_zabbix_api(client, method, params)
    return [str(row[id_field]) for row in rows if isinstance(row, dict) and row.get(id_field)]


def _trigger_hosts(client: GrafanaClientBase, trigger_ids: list[str]) -> dict[str, list[str]]:
    """Map each trigger ID to the names of the hosts it belongs to."""
    if not trigger_ids:
        return {}
    rows = _call_zabbix_api(
        client,
        "trigger.get",
        {
            "triggerids": trigger_ids,
            "output": ["triggerid"],
            "selectHosts": ["hostid", "host", "name"],
        },
    )
    hosts_by_trigger: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        hosts = row.get("hosts")
        hosts_by_trigger[str(row.get("triggerid"))] = [
            str(host.get("name") or host.get("host") or "")
            for host in (hosts if isinstance(hosts, list) else [])
            if isinstance(host, dict)
        ]
    return hosts_by_trigger


class ZabbixMixin:
    """Mixin providing Zabbix problem and metric queries via a Grafana Zabbix datasource."""

    def query_zabbix_problems(  # type: ignore[misc]
        self: GrafanaClientBase,
        host_filter: str = "",
        group_filter: str = "",
        min_severity: int = 0,
        include_resolved: bool = True,
        time_range_minutes: int = 60,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Query Zabbix problems (active alerts, plus recently resolved ones).

        Args:
            host_filter: Host name or technical name to match; ``*`` is a wildcard.
            group_filter: Host group name to match; ``*`` is a wildcard.
            min_severity: Lowest severity to return, 0 (not classified) to 5 (disaster).
            include_resolved: Also return problems resolved inside the time window.
            time_range_minutes: Window for resolved problems; active ones always appear.
            limit: Maximum raw problems to fetch, newest first.

        Returns:
            Dictionary with normalized problems and counts.
        """
        if not self.is_configured:
            return {
                "success": False,
                "error": f"Grafana client not configured for account '{self.account_id}'",
                "problems": [],
            }

        limit = max(1, min(limit, _MAX_PROBLEM_LIMIT))
        window_minutes = max(1, min(time_range_minutes, _MAX_RANGE_MINUTES))
        severity = max(0, min(min_severity, _MAX_SEVERITY))
        base: dict[str, Any] = {
            "problems": [],
            "total_problems": 0,
            "active_problems": 0,
            "truncated": False,
        }

        try:
            params: dict[str, Any] = {
                "output": "extend",
                "recent": include_resolved,
                "selectTags": "extend",
                "sortfield": ["eventid"],
                "sortorder": "DESC",
                "limit": limit,
            }
            if severity > 0:
                params["severities"] = list(range(severity, _MAX_SEVERITY + 1))
            if host_filter:
                host_ids = _lookup_ids(
                    self, "host.get", "hostid", {"host": [host_filter], "name": [host_filter]}
                )
                if not host_ids:
                    return {"success": True, **base, "account_id": self.account_id}
                params["hostids"] = host_ids
            if group_filter:
                group_ids = _lookup_ids(self, "hostgroup.get", "groupid", {"name": [group_filter]})
                if not group_ids:
                    return {"success": True, **base, "account_id": self.account_id}
                params["groupids"] = group_ids

            raw = _call_zabbix_api(self, "problem.get", params)
            window_start = int(time.time()) - window_minutes * 60
            # `recent` returns every recently resolved problem, so the window is
            # applied here; unresolved problems always stay, however old.
            kept = [
                row
                for row in raw
                if isinstance(row, dict)
                and (not is_resolved(row) or last_activity_seconds(row) >= window_start)
            ]
            trigger_ids = sorted({str(row["objectid"]) for row in kept if row.get("objectid")})
            hosts = _trigger_hosts(self, trigger_ids)
            problems = [normalize_problem(row, hosts) for row in kept]
            return {
                "success": True,
                "problems": problems,
                "total_problems": len(problems),
                "active_problems": sum(1 for item in problems if item["status"] == "problem"),
                "truncated": len(raw) >= limit,
                "account_id": self.account_id,
            }
        except Exception as e:
            return _failure(e, **base)

    def query_zabbix_metrics(  # type: ignore[misc]
        self: GrafanaClientBase,
        item_filter: str,
        host_filter: str = "",
        group_filter: str = "",
        time_range_minutes: int = 60,
    ) -> dict[str, Any]:
        """Query Zabbix item history through the datasource's metrics query.

        Args:
            item_filter: Item name, or ``/regex/``, e.g. ``CPU utilization``.
            host_filter: Host name or ``/regex/``; empty matches every host.
            group_filter: Host group name or ``/regex/``; empty matches every group.
            time_range_minutes: Lookback window in minutes (default 60).

        Returns:
            Dictionary with one summarized series per matching item.
        """
        if not self.is_configured:
            return {
                "success": False,
                "error": f"Grafana client not configured for account '{self.account_id}'",
                "metrics": [],
            }

        window_minutes = max(1, min(time_range_minutes, _MAX_RANGE_MINUTES))
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - window_minutes * 60 * 1000
        group = group_filter or _MATCH_ALL
        host = host_filter or _MATCH_ALL

        body = {
            "queries": [
                {
                    "refId": _REF_ID,
                    "datasource": {"uid": self.zabbix_datasource_uid},
                    "queryType": _METRICS_QUERY_TYPE,
                    "group": {"filter": group},
                    "host": {"filter": host},
                    "application": {"filter": ""},
                    "itemTag": {"filter": ""},
                    "item": {"filter": item_filter},
                    "functions": [],
                    "options": {
                        "showDisabledItems": False,
                        "skipEmptyValues": False,
                        "disableDataAlignment": False,
                        "useZabbixValueMapping": True,
                    },
                    "maxDataPoints": _MAX_DATA_POINTS,
                    "intervalMs": max(_MIN_INTERVAL_MS, (end_ms - start_ms) // _MAX_DATA_POINTS),
                }
            ],
            "from": str(start_ms),
            "to": str(end_ms),
        }
        query = {"group": group, "host": host, "item": item_filter}

        try:
            data = self._make_post_request(
                f"{self.instance_url}{_QUERY_PATH}",
                json_body=body,
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            query_error = extract_query_error(data, _REF_ID)
            if query_error:
                return {"success": False, "error": query_error, "response": "", "metrics": []}

            frames = data["results"][_REF_ID].get("frames") or []
            series, total_series = frames_to_series(
                frames, max_series=_MAX_SERIES, max_points=_MAX_POINTS_PER_SERIES
            )
            return {
                "success": True,
                "metrics": series,
                "total_series": total_series,
                "truncated": total_series > len(series),
                "query": query,
                "account_id": self.account_id,
            }
        except Exception as e:
            return _failure(e, metrics=[])
