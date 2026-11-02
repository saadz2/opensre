"""Unit tests for PagerDuty integration config, catalog, and env-var loader."""

from __future__ import annotations

from http import HTTPStatus
from unittest.mock import patch

import httpx
import pytest
from pydantic import ValidationError

from integrations.config_models import PagerDutyIntegrationConfig
from integrations.pagerduty.client import PagerDutyClient


@pytest.mark.parametrize(
    ("configured_ids", "requested_ids", "expected_ids"),
    [
        (None, None, []),
        ("", None, []),
        ("   ", ["POTHER"], ["POTHER"]),
        ("PONE", None, ["PONE"]),
        (" PONE, PTWO, PONE, ", [], ["PONE", "PTWO"]),
        ("PONE,PTWO", ["PTWO"], ["PTWO"]),
    ],
)
def test_incident_list_service_scope(
    monkeypatch: pytest.MonkeyPatch,
    configured_ids: str | None,
    requested_ids: list[str] | None,
    expected_ids: list[str],
) -> None:
    if configured_ids is None:
        monkeypatch.delenv("PAGERDUTY_SERVICE_IDS", raising=False)
    else:
        monkeypatch.setenv("PAGERDUTY_SERVICE_IDS", configured_ids)
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(HTTPStatus.OK, json={"incidents": []})

    with PagerDutyClient(PagerDutyIntegrationConfig(api_key="test-key")) as client:
        client._client = httpx.Client(
            base_url=client.config.base_url, transport=httpx.MockTransport(respond)
        )
        result = client.list_incidents(service_ids=requested_ids, statuses=["triggered"], limit=5)

    assert result["success"] is True
    assert len(requests) == 1
    assert requests[0].url.params.get_list("service_ids[]") == expected_ids
    assert requests[0].url.params.get_list("statuses[]") == ["triggered"]
    assert requests[0].url.params["limit"] == "5"


@pytest.mark.parametrize(
    ("configured_ids", "requested_ids"),
    [("PONE,PTWO", ["POTHER"]), ("PONE", ["PONE", "POTHER"]), (", ,", None)],
)
def test_incident_list_rejects_scope_widening_without_http(
    monkeypatch: pytest.MonkeyPatch, configured_ids: str, requested_ids: list[str] | None
) -> None:
    monkeypatch.setenv("PAGERDUTY_SERVICE_IDS", configured_ids)
    with PagerDutyClient(PagerDutyIntegrationConfig(api_key="test-key")) as client:
        result = client.list_incidents(service_ids=requested_ids)
        assert client._client is None
    assert result["success"] is False
    assert result["error"]


class TestPagerDutyIntegrationConfig:
    """Tests for PagerDutyIntegrationConfig model validation."""

    def test_valid_config(self) -> None:
        config = PagerDutyIntegrationConfig(api_key="test-key")
        assert config.api_key == "test-key"
        assert config.base_url == "https://api.pagerduty.com"
        assert config.integration_id == ""

    def test_custom_base_url(self) -> None:
        config = PagerDutyIntegrationConfig(api_key="key", base_url="https://custom.pagerduty.com")
        assert config.base_url == "https://custom.pagerduty.com"

    def test_api_key_required(self) -> None:
        with pytest.raises(ValidationError):
            PagerDutyIntegrationConfig()  # type: ignore[call-arg]

    def test_headers_format(self) -> None:
        config = PagerDutyIntegrationConfig(api_key="my-token")
        assert config.headers == {
            "Authorization": "Token token=my-token",
            "Content-Type": "application/json",
        }

    def test_integration_id_stored(self) -> None:
        config = PagerDutyIntegrationConfig(api_key="k", integration_id="int-123")
        assert config.integration_id == "int-123"


class TestCatalogClassify:
    """Tests for _classify_service_instance handling of 'pagerduty' key."""

    def test_classify_valid_pagerduty(self) -> None:
        from integrations._catalog_impl import _classify_service_instance

        config, source = _classify_service_instance(
            "pagerduty",
            {"api_key": "pd-key", "base_url": "https://api.pagerduty.com"},
            record_id="rec-1",
        )
        assert source == "pagerduty"
        assert config is not None
        assert config.api_key == "pd-key"

    def test_classify_missing_api_key_returns_none(self) -> None:
        from integrations._catalog_impl import _classify_service_instance

        config, source = _classify_service_instance(
            "pagerduty",
            {"api_key": "", "base_url": ""},
            record_id="rec-2",
        )
        assert config is None
        assert source is None

    def test_classify_uses_default_base_url(self) -> None:
        from integrations._catalog_impl import _classify_service_instance

        config, source = _classify_service_instance(
            "pagerduty",
            {"api_key": "key-1"},
            record_id="rec-3",
        )
        assert source == "pagerduty"
        assert config is not None
        assert config.base_url == "https://api.pagerduty.com"


class TestEnvLoader:
    """Tests for PAGERDUTY_API_KEY env-var loading."""

    @patch.dict("os.environ", {"PAGERDUTY_API_KEY": "env-key"}, clear=False)
    def test_env_loader_picks_up_api_key(self) -> None:
        from integrations._catalog_impl import load_env_integrations

        integrations = load_env_integrations()
        pd_records = [r for r in integrations if r.get("service") == "pagerduty"]
        assert len(pd_records) == 1
        assert pd_records[0]["credentials"]["api_key"] == "env-key"

    @patch.dict("os.environ", {}, clear=False)
    def test_env_loader_skips_when_no_key(self) -> None:
        import os

        os.environ.pop("PAGERDUTY_API_KEY", None)
        from integrations._catalog_impl import load_env_integrations

        integrations = load_env_integrations()
        pd_records = [r for r in integrations if r.get("service") == "pagerduty"]
        assert len(pd_records) == 0
