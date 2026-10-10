"""Resolve an eligible app connection or explicitly configured local GitHub PAT."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from config.constants.github import (
    GITHUB_CONNECTION_ORIGIN_TAG,
    GITHUB_PAT_ORIGIN,
    GITHUB_WEBAPP_ORIGIN,
    OPENSRE_GITHUB_PAT_ENV,
)
from core.tool import availability_view


def github_selection_failed(sources: Mapping[str, Any]) -> bool:
    """True when the chosen GitHub grant is missing or unusable.

    ``select_github_connection`` marks that on ``sources["github"]``; GitHub
    tools are then withdrawn and no other token stands in for the grant.
    """
    github = sources.get("github")
    return isinstance(github, Mapping) and bool(github.get("connection_selection_error"))


def local_github_pat() -> str:
    """Resolve the explicitly configured local GitHub PAT without exposing its source."""
    from config.llm_credentials import resolve_env_credential

    return resolve_env_credential(OPENSRE_GITHUB_PAT_ENV)


def github_connection_origin(sources: Mapping[str, Any] | None = None) -> str:
    """Return the provenance of the selected app grant or explicit local PAT."""
    if sources is None or github_selection_failed(sources):
        return ""
    github = sources.get("github")
    if isinstance(github, Mapping):
        origin = str(github.get(GITHUB_CONNECTION_ORIGIN_TAG) or "")
        token = str(github.get("github_token") or github.get("auth_token") or "")
        if origin == GITHUB_WEBAPP_ORIGIN:
            return origin
        if origin == GITHUB_PAT_ORIGIN:
            return origin if token.strip() or local_github_pat() else ""
    return GITHUB_PAT_ORIGIN if local_github_pat() else ""


def github_rest_token(
    sources: Mapping[str, Any] | None = None,
    *,
    explicit: str | None = None,
    connection_origin: str | None = None,
) -> str:
    """Return an app token or explicit local PAT, preserving app selection failures."""
    if sources is not None:
        if github_selection_failed(sources):
            return ""
        github = sources.get("github")
        if isinstance(github, Mapping):
            source_origin = str(github.get(GITHUB_CONNECTION_ORIGIN_TAG) or "")
            if connection_origin is None:
                connection_origin = source_origin
            if explicit is None:
                explicit = str(github.get("github_token") or github.get("auth_token") or "")
    if connection_origin == GITHUB_WEBAPP_ORIGIN:
        return (explicit or "").strip()
    if connection_origin == GITHUB_PAT_ORIGIN:
        return (explicit or local_github_pat()).strip()
    if connection_origin is not None:
        return ""
    if explicit:
        return ""
    return local_github_pat()


def resolved_github_rest_token(resolved_integrations: Mapping[str, Any]) -> str:
    """The token a GitHub REST tool run on ``resolved_integrations`` is handed; ``""`` when none."""
    return github_rest_token(availability_view(dict(resolved_integrations)))


def has_github_rest_token(resolved_integrations: Mapping[str, Any]) -> bool:
    """True when a GitHub REST tool run on ``resolved_integrations`` would find a token."""
    return bool(resolved_github_rest_token(resolved_integrations))


__all__ = [
    "github_connection_origin",
    "github_rest_token",
    "github_selection_failed",
    "has_github_rest_token",
    "local_github_pat",
    "resolved_github_rest_token",
]
