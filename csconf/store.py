from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from csconf.models import Paper


class ShrinkRejected(Exception):
    """新结果比已存记录少。可能是半截响应，需人确认后用 --allow-shrink 放行。"""


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
            "{} {}: 新结果 {} 篇少于已存 {} 篇；确认无误后用 --allow-shrink 放行".format(
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
