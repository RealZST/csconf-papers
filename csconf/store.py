from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from csconf.models import Paper


class ShrinkRejected(Exception):
    """Fewer papers than are already stored — possibly a truncated response.

    A person has to confirm the drop and re-run with --allow-shrink.
    """


def _path_for(root: Path, venue: str, year: int) -> Path:
    return Path(root) / "data" / str(year) / "{}.json".format(venue)


def load_raw(root: Path, venue: str, year: int) -> Optional[Dict[str, Any]]:
    path = _path_for(root, venue, year)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_papers(root: Path, venue: str, year: int) -> List[Dict[str, Any]]:
    payload = load_raw(root, venue, year)
    return payload["papers"] if payload else []


def _link_cache_path(root: Path) -> Path:
    return Path(root) / "data" / "link-cache.json"


def load_link_cache(root: Path) -> Dict[str, Any]:
    """Title to link, or to "looked and found nothing".

    Kept in the repo so CI does not repeat every lookup each month.
    """
    path = _link_cache_path(root)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_link_cache(root: Path, cache: Dict[str, Any]) -> Path:
    path = _link_cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Sorted: otherwise every diff reshuffles the whole file and hides which
    # entries were actually added this month.
    path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _pdf_cache_path(root: Path) -> Path:
    return Path(root) / "data" / "pdf-cache.json"


def load_pdf_cache(root: Path) -> Dict[str, bool]:
    """Which derived PDF URLs were confirmed to serve a PDF."""
    path = _pdf_cache_path(root)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_pdf_cache(root: Path, cache: Dict[str, bool]) -> Path:
    path = _pdf_cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _arxiv_cache_path(root: Path) -> Path:
    return Path(root) / "data" / "arxiv-cache.json"


def load_arxiv_cache(root: Path) -> Dict[str, Any]:
    """DOI to arXiv id, or to "asked and there is none"."""
    path = _arxiv_cache_path(root)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_arxiv_cache(root: Path, cache: Dict[str, Any]) -> Path:
    path = _arxiv_cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


# Bumped only if the shape below changes incompatibly, so a consumer can tell
# a format it understands from one it does not, rather than guessing from the
# keys it happens to find.
INDEX_SCHEMA = 1


def _index_path(root: Path) -> Path:
    return Path(root) / "data" / "index.json"


def scan_data_files(root: Path) -> List[Dict[str, Any]]:
    """Every stored venue-year, read from the files themselves.

    The glob requires a year directory between data/ and the file. That is what
    keeps link-cache.json, pdf-cache.json, arxiv-cache.json and index.json
    itself out of the result: they sit at the root of data/. Excluding them is
    a property of the shape, not a filter a later edit could drop.

    Reading and hashing the same bytes means the checksum always describes the
    payload that was parsed, and never a version written in between.
    """
    entries: List[Dict[str, Any]] = []
    for path in sorted((Path(root) / "data").glob("*/*.json")):
        raw = path.read_bytes()
        meta = json.loads(raw.decode("utf-8"))["meta"]
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "venue": meta["venue"],
                "year": meta["year"],
                "paper_count": meta["paper_count"],
                "updated": meta["updated"],
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return entries


def write_index(root: Path, generated: str) -> Path:
    """List the data files, because serving them does not.

    raw.githubusercontent.com hands over a file by path and has no way to ask
    what a directory holds, so a consumer cannot discover a newly added venue
    on its own. Publishing the listing as a file turns that into a fetch it
    already knows how to do.

    Built from disk on every command that writes a data file, never from what a
    run believed it wrote — the same rule as the README counts. A venue whose
    sync failed keeps the count and checksum of the bytes actually published,
    so the listing may lag DBLP but can never contradict this repository.
    """
    files = scan_data_files(root)
    payload = {
        "schema": INDEX_SCHEMA,
        "generated": generated,
        "paper_count": sum(entry["paper_count"] for entry in files),
        "files": files,
    }

    path = _index_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def rewrite_papers(root: Path, venue: str, year: int, papers: Sequence[Paper]) -> Path:
    """Replace only the papers, leaving meta untouched.

    Filling in links refetches no source data, so changing meta.updated would
    misreport when the list was collected. The count must not change either:
    if it does, the caller passed the wrong data, and since this path bypasses
    the shrink guard in write_venue_year, writing anyway would dismantle it.
    """
    payload = load_raw(root, venue, year)
    if payload is None:
        raise FileNotFoundError("{} {} has no stored data yet".format(venue, year))
    if len(papers) != len(payload["papers"]):
        raise ValueError(
            "{} {}: rewrite_papers must not change the paper count ({} -> {})".format(
                venue, year, len(payload["papers"]), len(papers)
            )
        )

    payload["papers"] = [p.to_dict() for p in papers]
    path = _path_for(root, venue, year)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def write_venue_year(
    root: Path,
    venue: str,
    year: int,
    papers: Sequence[Paper],
    source_keys: Sequence[str],
    note: Optional[str],
    updated: str,
    allow_shrink: bool = False,
) -> Path:
    existing = load_papers(root, venue, year)
    if not allow_shrink and len(papers) < len(existing):
        raise ShrinkRejected(
            "{} {}: {} papers is fewer than the {} already stored; confirm and "
            "re-run with --allow-shrink".format(
                venue, year, len(papers), len(existing)
            )
        )

    payload = {
        "meta": {
            "venue": venue,
            "year": year,
            "source_keys": list(source_keys),
            "paper_count": len(papers),
            "note": note,
            "updated": updated,
        },
        "papers": [p.to_dict() for p in papers],
    }

    path = _path_for(root, venue, year)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path
