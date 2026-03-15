"""ArXiv search tool for novelty checks and related-work lookups."""

from __future__ import annotations

from textwrap import shorten
from urllib.parse import quote
from urllib.request import urlopen
import xml.etree.ElementTree as ET

ARXIV_API_URL = "http://export.arxiv.org/api/query"
ATOM_NAMESPACE = {"atom": "http://www.w3.org/2005/Atom"}


def _clean_text(value: str | None) -> str:
    """Collapse XML text blocks into a single readable line."""

    return " ".join((value or "").split())


def search_arxiv(query: str, max_results: int = 3) -> str:
    """Search the ArXiv API and return a concise related-work summary."""

    normalized_query = _clean_text(query)
    if not normalized_query:
        return "ArXiv search skipped because no query was provided."

    safe_max_results = max(1, min(max_results, 5))
    encoded_query = quote(normalized_query)
    request_url = (
        f"{ARXIV_API_URL}?search_query=all:{encoded_query}&start=0&max_results={safe_max_results}"
    )

    try:
        with urlopen(request_url, timeout=15) as response:
            payload = response.read()
    except Exception as exc:
        return f"ArXiv search failed for query '{normalized_query}': {exc}"

    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        return f"ArXiv search returned unreadable XML for query '{normalized_query}': {exc}"

    entries = root.findall("atom:entry", ATOM_NAMESPACE)
    if not entries:
        return f"No ArXiv results found for query '{normalized_query}'."

    lines = [f"ArXiv results for query: {normalized_query}"]
    for index, entry in enumerate(entries, start=1):
        title = _clean_text(entry.findtext("atom:title", default="", namespaces=ATOM_NAMESPACE))
        published = _clean_text(
            entry.findtext("atom:published", default="", namespaces=ATOM_NAMESPACE)
        )
        summary = _clean_text(entry.findtext("atom:summary", default="", namespaces=ATOM_NAMESPACE))
        authors = [
            _clean_text(author.findtext("atom:name", default="", namespaces=ATOM_NAMESPACE))
            for author in entry.findall("atom:author", ATOM_NAMESPACE)
        ]
        author_text = ", ".join(author for author in authors if author) or "Unknown authors"

        lines.extend(
            [
                "",
                f"{index}. Title: {title or 'Untitled'}",
                f"   Authors: {author_text}",
                f"   Published: {published or 'Unknown'}",
                f"   Summary: {shorten(summary or 'No summary available.', width=700, placeholder='...')}",
            ]
        )

    return "\n".join(lines)
