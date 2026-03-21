"""ArXiv search tool for novelty checks and related-work lookups."""

from __future__ import annotations

import json
from textwrap import shorten
from urllib.parse import quote
from urllib.request import urlopen
import xml.etree.ElementTree as ET

ARXIV_API_URL = "http://export.arxiv.org/api/query"
ATOM_NAMESPACE = {"atom": "http://www.w3.org/2005/Atom"}


def _clean_text(value: str | None) -> str:
    """Collapse XML text blocks into a single readable line."""

    return " ".join((value or "").split())


def _json_response(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def search_arxiv(query: str, max_results: int = 3) -> str:
    """Search the ArXiv API and return a JSON payload of normalized results."""

    normalized_query = _clean_text(query)
    if not normalized_query:
        return _json_response(
            {
                "tool": "search_arxiv",
                "status": "error",
                "query": normalized_query,
                "summary": "ArXiv search skipped because no query was provided.",
                "results": [],
            }
        )

    safe_max_results = max(1, min(max_results, 5))
    encoded_query = quote(normalized_query)
    request_url = (
        f"{ARXIV_API_URL}?search_query=all:{encoded_query}&start=0&max_results={safe_max_results}"
    )

    try:
        with urlopen(request_url, timeout=15) as response:
            payload = response.read()
        root = ET.fromstring(payload)
    except Exception as exc:
        print(f"ArXiv search error for query '{normalized_query}': {exc}")
        return _json_response(
            {
                "tool": "search_arxiv",
                "status": "error",
                "query": normalized_query,
                "summary": f"ArXiv search failed due to network or parsing error ({exc}).",
                "results": [],
            }
        )

    entries = root.findall("atom:entry", ATOM_NAMESPACE)
    if not entries:
        return _json_response(
            {
                "tool": "search_arxiv",
                "status": "no_results",
                "query": normalized_query,
                "summary": f"No ArXiv results found for query '{normalized_query}'.",
                "results": [],
            }
        )

    results: list[dict[str, object]] = []
    for index, entry in enumerate(entries, start=1):
        title = _clean_text(entry.findtext("atom:title", default="", namespaces=ATOM_NAMESPACE))
        published = _clean_text(
            entry.findtext("atom:published", default="", namespaces=ATOM_NAMESPACE)
        )
        summary = _clean_text(entry.findtext("atom:summary", default="", namespaces=ATOM_NAMESPACE))
        entry_id = _clean_text(entry.findtext("atom:id", default="", namespaces=ATOM_NAMESPACE))
        authors = [
            _clean_text(author.findtext("atom:name", default="", namespaces=ATOM_NAMESPACE))
            for author in entry.findall("atom:author", ATOM_NAMESPACE)
        ]
        categories = [
            _clean_text(category.attrib.get("term"))
            for category in entry.findall("atom:category", ATOM_NAMESPACE)
            if _clean_text(category.attrib.get("term"))
        ]
        arxiv_id = entry_id.rsplit("/", 1)[-1] if entry_id else None

        results.append(
            {
                "result_rank": index,
                "title": title or "Untitled",
                "authors": [author for author in authors if author],
                "published_date": published or None,
                "arxiv_id": arxiv_id,
                "categories": categories,
                "source_url": entry_id or None,
                "summary": shorten(summary or "No summary available.", width=700, placeholder="..."),
            }
        )

    top_result = results[0]
    summary = (
        f"Top ArXiv result for '{normalized_query}' is '{top_result['title']}' "
        f"published on {top_result.get('published_date') or 'an unknown date'}."
    )
    return _json_response(
        {
            "tool": "search_arxiv",
            "status": "ok",
            "query": normalized_query,
            "summary": summary,
            "results": results,
        }
    )
