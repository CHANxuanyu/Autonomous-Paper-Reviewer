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


def _json_response(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _fetch_json(url: str) -> dict[str, object] | list[object] | None:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": GITHUB_USER_AGENT,
        },
    )
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_optional_json(url: str) -> dict[str, object] | list[object] | None:
    try:
        return _fetch_json(url)
    except Exception:
        return None


def check_github_repo(repo_url: str) -> str:
    """Check whether a GitHub repository exists and return a JSON evidence payload."""

    normalized_repo_url = (repo_url or "").strip().rstrip(").,;")
    if not normalized_repo_url:
        return _json_response(
            {
                "tool": "check_github_repo",
                "status": "error",
                "summary": "No GitHub repository URL was provided.",
                "repo": {
                    "repo_url": normalized_repo_url or None,
                    "repo_exists": None,
                },
            }
        )

    match = GITHUB_REPO_PATTERN.search(normalized_repo_url)
    if match is None:
        return _json_response(
            {
                "tool": "check_github_repo",
                "status": "error",
                "summary": "The provided GitHub URL could not be parsed as a repository link.",
                "repo": {
                    "repo_url": normalized_repo_url,
                    "repo_exists": None,
                },
            }
        )

    owner = match.group("owner")
    repo = match.group("repo")
    api_url = GITHUB_API_URL_TEMPLATE.format(owner=owner, repo=repo)

    try:
        payload = _fetch_json(api_url)
    except HTTPError as exc:
        print(f"GitHub repo check error for '{normalized_repo_url}': {exc}")
        if exc.code == 404:
            return _json_response(
                {
                    "tool": "check_github_repo",
                    "status": "not_found",
                    "summary": "GitHub repository not found (404 Not Found).",
                    "repo": {
                        "repo_url": normalized_repo_url,
                        "repo_exists": False,
                        "owner": owner,
                        "name": repo,
                    },
                }
            )
        if exc.code == 403:
            return _json_response(
                {
                    "tool": "check_github_repo",
                    "status": "error",
                    "summary": "GitHub API rate limit reached or access forbidden (403).",
                    "repo": {
                        "repo_url": normalized_repo_url,
                        "repo_exists": None,
                        "owner": owner,
                        "name": repo,
                    },
                }
            )
        return _json_response(
            {
                "tool": "check_github_repo",
                "status": "error",
                "summary": f"GitHub API request failed with HTTP {exc.code}.",
                "repo": {
                    "repo_url": normalized_repo_url,
                    "repo_exists": None,
                    "owner": owner,
                    "name": repo,
                },
            }
        )
    except URLError as exc:
        print(f"GitHub repo check error for '{normalized_repo_url}': {exc}")
        return _json_response(
            {
                "tool": "check_github_repo",
                "status": "error",
                "summary": f"GitHub network request failed ({exc.reason}).",
                "repo": {
                    "repo_url": normalized_repo_url,
                    "repo_exists": None,
                    "owner": owner,
                    "name": repo,
                },
            }
        )
    except Exception as exc:
        print(f"GitHub repo check error for '{normalized_repo_url}': {exc}")
        return _json_response(
            {
                "tool": "check_github_repo",
                "status": "error",
                "summary": f"Unexpected GitHub repository check failure ({exc}).",
                "repo": {
                    "repo_url": normalized_repo_url,
                    "repo_exists": None,
                    "owner": owner,
                    "name": repo,
                },
            }
        )

    readme_payload = _fetch_optional_json(f"{api_url}/readme")
    releases_payload = _fetch_optional_json(f"{api_url}/releases?per_page=1")
    languages_payload = _fetch_optional_json(str(payload.get("languages_url") or ""))

    stars = int(payload.get("stargazers_count") or 0)
    watchers = payload.get("subscribers_count")
    if watchers is None:
        watchers = payload.get("watchers_count")
    forks = int(payload.get("forks_count") or 0)
    updated_at = str(payload.get("updated_at") or "") or None
    pushed_at = str(payload.get("pushed_at") or "") or None
    open_issues_count = int(payload.get("open_issues_count") or 0)
    primary_language = str(payload.get("language") or "") or None
    languages = sorted(str(language) for language in (languages_payload or {}).keys()) if isinstance(languages_payload, dict) else []
    archived = bool(payload.get("archived"))
    disabled = bool(payload.get("disabled"))
    has_readme = bool(readme_payload) if readme_payload is not None else None
    has_releases = bool(releases_payload) if isinstance(releases_payload, list) else None
    default_branch = str(payload.get("default_branch") or "") or None

    summary = (
        f"GitHub repository {owner}/{repo} is reachable at {normalized_repo_url}. "
        f"Stars: {stars}, forks: {forks}, last updated: {updated_at or 'unknown'}, "
        f"default branch: {default_branch or 'unknown'}."
    )

    return _json_response(
        {
            "tool": "check_github_repo",
            "status": "ok",
            "summary": summary,
            "repo": {
                "repo_url": normalized_repo_url,
                "repo_exists": True,
                "owner": owner,
                "name": repo,
                "default_branch": default_branch,
                "stars": stars,
                "watchers": int(watchers) if watchers is not None else None,
                "forks": forks,
                "has_readme": has_readme,
                "has_releases": has_releases,
                "last_updated": updated_at,
                "pushed_at": pushed_at,
                "primary_language": primary_language,
                "languages": languages,
                "archived": archived,
                "disabled": disabled,
                "open_issues_count": open_issues_count,
                "summary": summary,
            },
        }
    )
