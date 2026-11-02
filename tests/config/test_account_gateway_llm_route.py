"""A hosted gateway reaches the webapp's LLM routes from its task environment alone."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from config.account import AccountRecord, account_llm_route, hosted_openai_env, resolve_account_token
from config.constants.account import (
    OPENSRE_ACCOUNT_METADATA_PATH_ENV,
    OPENSRE_ACCOUNT_TOKEN_ENV,
    OPENSRE_USE_HOSTED_LLM_ENV,
)
from config.constants.billing import WEBAPP_URL_ENV
from core.llm.factory import resolve_llm_route
from core.llm.shared.openai_responses import uses_responses_api


@pytest.fixture(autouse=True)
def _no_local_login(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(OPENSRE_ACCOUNT_METADATA_PATH_ENV, str(tmp_path / "account.json"))
    monkeypatch.delenv(OPENSRE_ACCOUNT_TOKEN_ENV, raising=False)
    monkeypatch.delenv(WEBAPP_URL_ENV, raising=False)
    monkeypatch.setenv(OPENSRE_USE_HOSTED_LLM_ENV, "1")


def test_the_injected_token_and_webapp_url_are_the_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OPENSRE_ACCOUNT_TOKEN_ENV, "osre_gw_org_A.signature")
    monkeypatch.setenv(WEBAPP_URL_ENV, "https://app.example/")

    route = account_llm_route()

    assert route is not None
    assert route.base_url == "https://app.example/api/llm/v1"
    # The served model family decides the OpenAI endpoint: a chat-completions
    # model name here makes every tool-using turn fail. The hosted default is
    # GPT-6.1 Sol, which requires the Responses API.
    assert route.model == "gpt-6.1-sol"
    assert uses_responses_api(route.model, "OPENAI_API_KEY")


@pytest.mark.parametrize("missing", [OPENSRE_ACCOUNT_TOKEN_ENV, WEBAPP_URL_ENV])
def test_either_half_missing_means_no_hosted_route(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.setenv(OPENSRE_ACCOUNT_TOKEN_ENV, "osre_gw_org_A.signature")
    monkeypatch.setenv(WEBAPP_URL_ENV, "https://app.example")
    monkeypatch.delenv(missing)

    assert account_llm_route() is None


def test_signed_in_account_can_use_local_llm_without_losing_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = AccountRecord(
        user_id="user_local",
        organization_id=None,
        email=None,
        app_url="https://app.example",
        signed_in_at="2026-10-10T00:00:00Z",
        token_expires_at="2026-10-11T00:00:00Z",
    )

    def _load_account_record() -> AccountRecord:
        return record

    monkeypatch.setattr("config.account.load_account_record", _load_account_record)
    monkeypatch.setenv(OPENSRE_ACCOUNT_TOKEN_ENV, "osre_local.signature")
    assert account_llm_route() is not None

    monkeypatch.setenv(OPENSRE_USE_HOSTED_LLM_ENV, "0")

    assert account_llm_route() is None
    assert hosted_openai_env() is None
    assert resolve_account_token() == "osre_local.signature"

    monkeypatch.setattr(
        "config.llm_settings.resolve_llm_settings", lambda: SimpleNamespace(provider="ollama")
    )
    assert resolve_llm_route().provider == "ollama"
