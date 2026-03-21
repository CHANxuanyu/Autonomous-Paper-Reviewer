"""Materialize the checked-in curated benchmark slice into local PDF fixtures."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_ROOT = PROJECT_ROOT / "benchmarks" / "data"
DEFAULT_MANIFEST_PATH = BENCHMARK_ROOT / "curated_tool_needed_v1_sources.json"
USER_AGENT = "Academic-Paper-Analyzer-Benchmark/1.0"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download or copy the PDF fixtures used by the curated benchmark slice."
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST_PATH),
        help="Path to the curated slice source manifest.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download or re-copy files even if the target PDF already exists.",
    )
    return parser.parse_args()


def _project_path(value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate


def _download_file(download_url: str, target_path: Path) -> None:
    request = Request(download_url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response, target_path.open("wb") as output_file:
        shutil.copyfileobj(response, output_file)


def _materialize_entry(entry: dict[str, object], *, force: bool) -> tuple[str, str]:
    paper_id = str(entry.get("paper_id") or "unknown-paper")
    title = str(entry.get("title") or paper_id)
    target_path = _project_path(str(entry.get("pdf_path") or ""))
    if not str(entry.get("pdf_path") or "").strip():
        return paper_id, "missing_target_path"

    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists() and not force:
        return paper_id, "already_present"

    download_url = str(entry.get("download_url") or "").strip()
    if download_url:
        try:
            _download_file(download_url, target_path)
            return paper_id, "downloaded"
        except Exception:
            if target_path.exists():
                target_path.unlink(missing_ok=True)

    for candidate_value in entry.get("local_candidate_paths") or []:
        candidate_path = _project_path(str(candidate_value))
        if candidate_path.exists():
            shutil.copyfile(candidate_path, target_path)
            return paper_id, "copied_from_local_fixture"

    source_url = str(entry.get("source_url") or "").strip() or "no source URL provided"
    print(
        f"[missing] {paper_id}: could not materialize '{title}'. "
        f"Add the PDF manually at {target_path} or use the source page {source_url}."
    )
    return paper_id, "missing_manual_fixture"


def main() -> None:
    args = _parse_args()
    manifest_path = _project_path(str(args.manifest))
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    papers = payload.get("papers") if isinstance(payload, dict) else None
    if not isinstance(papers, list):
        raise ValueError(f"Invalid curated slice manifest: {manifest_path}")

    results: dict[str, str] = {}
    for entry in papers:
        if not isinstance(entry, dict):
            continue
        paper_id, status = _materialize_entry(entry, force=bool(args.force))
        results[paper_id] = status
        print(f"[{status}] {paper_id}")

    missing = [paper_id for paper_id, status in results.items() if status == "missing_manual_fixture"]
    if missing:
        raise SystemExit(
            "Some benchmark PDFs are still missing: " + ", ".join(missing)
        )


if __name__ == "__main__":
    main()
