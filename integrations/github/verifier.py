"""GitHub MCP integration verifier.

Reports credential-less records as ``missing`` rather than ``failed`` so
a stale store entry with no auth token surfaces as not-configured instead
of a confusing 401.
"""

from __future__ import annotations

from typing import Any

from config.constants.github import GITHUB_CONNECTION_ORIGIN_TAG, GITHUB_PAT_ORIGIN
from integrations.github.client import GitHubApiError, GitHubRestClient
from integrations.github.mcp import build_github_mcp_config, validate_github_mcp_config
from integrations.github.rest_token import local_github_pat
from integrations.verification import register_verifier, result


@register_verifier("github")
def verify_github(source: str, config: dict[str, Any]) -> dict[str, str]:
    origin = config.get(GITHUB_CONNECTION_ORIGIN_TAG)
    if origin == GITHUB_PAT_ORIGIN or (origin != "webapp" and local_github_pat()):
        token = str(config.get("auth_token") or local_github_pat())
        try:
            profile = GitHubRestClient(token).request("GET", "/user")
        except GitHubApiError as exc:
            detail = "GitHub PAT verification failed; check token validity and repository access."
            if exc.status_code is not None:
                detail += f" GitHub returned HTTP {exc.status_code}."
            return result("github", source, "failed", detail)
        login = (
            str(profile.get("login") or "GitHub user")
            if isinstance(profile, dict)
            else "GitHub user"
        )
        return result("github", source, "passed", f"Local GitHub PAT is valid for {login}.")
    mcp_config = dict(config)
    mcp_config.pop(GITHUB_CONNECTION_ORIGIN_TAG, None)
    normalized_config = build_github_mcp_config(mcp_config)
    validation_result = validate_github_mcp_config(normalized_config)
    if not validation_result.ok and validation_result.failure_category == "not_configured":
        return result("github", source, "missing", validation_result.detail)
    return result(
        "github",
        source,
        "passed" if validation_result.ok else "failed",
        validation_result.detail,
    )
