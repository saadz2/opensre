"""Credential extraction for the GitHub CLI tool."""

from __future__ import annotations

from typing import Any

from config.constants.github import GITHUB_CONNECTION_ID_PARAM, GITHUB_CONNECTION_ORIGIN_PARAM
from integrations.github.rest_token import github_connection_origin, github_rest_token

# Keys ``extract_params`` may inject that must beat model-supplied kwargs.
# Narrower than ``integrations.github.helpers.GITHUB_INJECTED_PARAMS``: the CLI
# protects only the token; owner/repo stay model-overridable.
GITHUB_CLI_INJECTED_PARAMS: tuple[str, ...] = (
    "github_token",
    "github_connection_id",
    "github_connection_origin",
)


def github_source_available(sources: dict[str, dict]) -> bool:
    from integrations.github.rest_token import has_github_rest_token

    return has_github_rest_token(sources)


def github_creds(gh: dict[str, Any]) -> dict[str, Any]:
    """Map classified GitHub integration fields to tool credential kwargs."""
    origin = github_connection_origin({"github": gh})
    token = github_rest_token({"github": gh})
    if not token or not origin:
        return {}
    creds: dict[str, Any] = {}
    if gh.get("connection_id"):
        creds[GITHUB_CONNECTION_ID_PARAM] = gh["connection_id"]
    if token:
        creds["github_token"] = token
    creds[GITHUB_CONNECTION_ORIGIN_PARAM] = origin
    return creds


__all__ = [
    "GITHUB_CLI_INJECTED_PARAMS",
    "github_creds",
    "github_source_available",
]
