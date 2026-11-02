"""Zabbix datasource discovery for the Grafana client."""

from __future__ import annotations

from unittest.mock import patch

from integrations.grafana.base import GrafanaClientBase
from integrations.grafana.config import GrafanaAccountConfig


def _client() -> GrafanaClientBase:
    return GrafanaClientBase(
        GrafanaAccountConfig(account_id="t", instance_url="http://grafana", read_token="tok")
    )


def _discover(datasources: list[dict]) -> dict[str, str]:
    client = _client()
    with patch.object(client, "_make_get_request", return_value=datasources):
        return client.discover_datasource_uids()


def test_zabbix_plugin_is_discovered_without_displacing_the_prometheus_datasource() -> None:
    discovered = _discover(
        [
            {"uid": "prom-1", "name": "Prometheus", "type": "prometheus"},
            {"uid": "zbx-1", "name": "Zabbix", "type": "alexanderzobnin-zabbix-datasource"},
        ]
    )

    assert discovered["zabbix_uid"] == "zbx-1"
    assert discovered["mimir_uid"] == "prom-1"


def test_zabbix_only_grafana_discovers_no_prometheus_datasource() -> None:
    discovered = _discover(
        [{"uid": "zbx-1", "name": "Zabbix", "type": "alexanderzobnin-zabbix-datasource"}]
    )

    assert discovered == {"zabbix_uid": "zbx-1"}


def test_default_zabbix_datasource_wins_over_others() -> None:
    discovered = _discover(
        [
            {"uid": "zbx-a", "name": "zabbix-a", "type": "alexanderzobnin-zabbix-datasource"},
            {
                "uid": "zbx-b",
                "name": "zabbix-b",
                "type": "alexanderzobnin-zabbix-datasource",
                "isDefault": True,
            },
        ]
    )

    assert discovered["zabbix_uid"] == "zbx-b"
