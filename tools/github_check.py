"""GitHub repository verification tool for code reproducibility checks."""

from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

GITHUB_REPO_PATTERN = re.compile(
    r"https?://(?:www\.)?github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?(?:/|$)",
    re.IGNORECASE,
)
GITHUB_API_URL_TEMPLATE = "https://api.github.com/repos/{owner}/{repo}"
GITHUB_USER_AGENT = "AcademicPaperReviewer/1.0"


def check_github_repo(repo_url: str) -> str:
    """Check whether a GitHub repository exists and summarize basic health signals."""

    normalized_repo_url = (repo_url or "").strip().rstrip(").,;")
    if not normalized_repo_url:
        return "Tool Error: No GitHub repository URL was provided. Please rely solely on the provided internal PDF context."

    match = GITHUB_REPO_PATTERN.search(normalized_repo_url)
    if match is None:
        return (
            "Tool Error: The provided GitHub URL could not be parsed as a repository link. "
            "Please rely solely on the provided internal PDF context."
        )

    owner = match.group("owner")
    repo = match.group("repo")
    api_url = GITHUB_API_URL_TEMPLATE.format(owner=owner, repo=repo)
    request = Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": GITHUB_USER_AGENT,
        },
    )

    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        print(f"GitHub repo check error for '{normalized_repo_url}': {exc}")
        if exc.code == 404:
            return (
                "Tool Error: GitHub repository not found (404 Not Found). "
                "Please rely solely on the provided internal PDF context."
            )
        if exc.code == 403:
            return (
                "Tool Error: GitHub API rate limit reached or access forbidden (403). "
                "Please rely solely on the provided internal PDF context."
            )
        return (
            f"Tool Error: GitHub API request failed with HTTP {exc.code}. "
            "Please rely solely on the provided internal PDF context."
        )
    except URLError as exc:
        print(f"GitHub repo check error for '{normalized_repo_url}': {exc}")
        return (
            f"Tool Error: GitHub network request failed ({exc.reason}). "
            "Please rely solely on the provided internal PDF context."
        )
    except Exception as exc:
        print(f"GitHub repo check error for '{normalized_repo_url}': {exc}")
        return (
            f"Tool Error: Unexpected GitHub repository check failure ({exc}). "
            "Please rely solely on the provided internal PDF context."
        )

    stars = int(payload.get("stargazers_count") or 0)
    created_at = str(payload.get("created_at") or "unknown")
    updated_at = str(payload.get("updated_at") or "unknown")
    has_issues = bool(payload.get("has_issues"))
    size_kb = int(payload.get("size") or 0)
    archived = bool(payload.get("archived"))
    open_issues_count = int(payload.get("open_issues_count") or 0)

    issues_status = "enabled" if has_issues else "disabled"
    archive_status = "archived" if archived else "active"

    return (
        f"GitHub repository check for {owner}/{repo}: the repository is publicly reachable at "
        f"{normalized_repo_url}. It currently has {stars} stars, was created on {created_at}, "
        f"and was last updated on {updated_at}. Issue tracking is {issues_status} with "
        f"{open_issues_count} open issues reported. The repository size is {size_kb} KB and its "
        f"status appears {archive_status}. Use these signals to comment on code availability, "
        "maintenance activity, and reproducibility confidence."
    )
