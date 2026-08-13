"""Attach the arXiv preprint id for papers that have a DOI.

The ACM Digital Library is open access, so these papers are already free to
read — this is not about access. It is about machine access: dl.acm.org answers
automated requests with 403, so nothing can fetch those PDFs on a reader's
behalf, while arxiv.org serves them to anyone (see the host matrix in the
design notes). Roughly 40% of the ACM papers here have an arXiv preprint, and
holding its id costs two HTTP requests for the whole corpus.

Lookups go through Semantic Scholar's batch endpoint keyed by DOI. A DOI is an
exact identifier, so the arXiv id that comes back belongs to that exact paper —
none of the title-matching risk that makes csconf.enrich so careful. Papers
without a DOI are simply skipped rather than matched by title.

A preprint is not the version of record: it can differ from the camera-ready in
results, sections and wording. It is published alongside the official link and
labelled as a preprint, never in place of it.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from dataclasses import replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

from csconf import http
from csconf.models import Paper

BATCH_ENDPOINT = "https://api.semanticscholar.org/graph/v1/paper/batch"
BATCH_FIELDS = "title,externalIds"

# The endpoint caps a batch at 500 ids.
BATCH_SIZE = 500

# A paper can reach arXiv after its camera-ready, so a miss is not permanent.
MISS_RETRY_DAYS = 90

# Requests, not papers: the whole corpus is two of them.
DEFAULT_BUDGET = 8


def batch_url() -> str:
    return "{}?fields={}".format(BATCH_ENDPOINT, BATCH_FIELDS)


def _is_stale(checked: Optional[str], today: str) -> bool:
    if not checked:
        return True
    try:
        age = dt.date.fromisoformat(today) - dt.date.fromisoformat(checked)
    except ValueError:
        return True
    return age.days >= MISS_RETRY_DAYS


def _chunks(items: Sequence[Any], size: int) -> List[Sequence[Any]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def fetch_arxiv_ids(dois: Sequence[str], fetcher) -> Optional[Dict[str, Optional[str]]]:
    """Map DOIs to arXiv ids. Returns None if the batch could not be answered.

    None and "no preprint" have to stay distinguishable: a failed request must
    not be recorded as an absence, or a blip suppresses the whole batch for a
    quarter.
    """
    try:
        payload = fetcher.post_json(batch_url(), {"ids": ["DOI:" + d for d in dois]})
    except (http.RateLimited, http.HttpError, http.NotFound) as exc:
        print("  preprint batch failed: {}".format(exc), file=sys.stderr)
        return None

    try:
        records = json.loads(payload)
    except ValueError as exc:
        print("  preprint batch returned non-JSON: {}".format(exc), file=sys.stderr)
        return None

    if not isinstance(records, list) or len(records) != len(dois):
        # Results are positional: one slot per requested id, null when unknown.
        # A short list would silently shift every id after the gap onto the
        # wrong paper, so refuse the whole batch instead of guessing.
        print(
            "  preprint batch returned {} slots for {} ids; refusing to map".format(
                len(records) if isinstance(records, list) else "non-list", len(dois)
            ),
            file=sys.stderr,
        )
        return None

    result: Dict[str, Optional[str]] = {}
    for doi, record in zip(dois, records):
        external = (record or {}).get("externalIds") or {}
        result[doi] = external.get("ArXiv")
    return result


def fill_arxiv_ids(
    papers: Sequence[Paper],
    cache: Dict[str, Any],
    fetcher,
    today: str,
    budget: int = DEFAULT_BUDGET,
) -> Tuple[List[Paper], Dict[str, Any], Dict[str, Any]]:
    """Fill arxiv_id where a DOI maps to one. Returns (papers, cache, stats)."""
    cache = dict(cache)
    stats = {
        "found": 0,
        "cached": 0,
        "missing": 0,
        "unavailable": 0,
        "requests": 0,
        "budget_exhausted": False,
    }

    wanted: List[str] = []
    for paper in papers:
        if paper.arxiv_id or not paper.doi:
            continue
        entry = cache.get(paper.doi)
        if entry and (entry.get("arxiv_id") or not _is_stale(entry.get("checked"), today)):
            continue
        if paper.doi not in wanted:
            wanted.append(paper.doi)

    for chunk in _chunks(wanted, BATCH_SIZE):
        if stats["requests"] >= budget:
            stats["budget_exhausted"] = True
            break
        stats["requests"] += 1
        found = fetch_arxiv_ids(chunk, fetcher)
        if found is None:
            stats["unavailable"] += 1
            continue
        for doi, arxiv_id in found.items():
            cache[doi] = {"arxiv_id": arxiv_id, "checked": today}

    result: List[Paper] = []
    for paper in papers:
        if paper.arxiv_id or not paper.doi:
            result.append(paper)
            continue
        entry = cache.get(paper.doi) or {}
        arxiv_id = entry.get("arxiv_id")
        if arxiv_id:
            stats["found" if paper.doi in wanted else "cached"] += 1
            result.append(replace(paper, arxiv_id=arxiv_id))
        else:
            if entry:
                stats["missing"] += 1
            result.append(paper)

    return result, cache, stats


def abs_url(arxiv_id: str) -> str:
    return "https://arxiv.org/abs/{}".format(arxiv_id)


def pdf_url(arxiv_id: str) -> str:
    return "https://arxiv.org/pdf/{}".format(arxiv_id)
