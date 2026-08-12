"""Find a link to read a paper by, for papers that arrived without one.

Editions scraped from the conference site (because DBLP has not indexed them
yet) carry titles and authors only: the SIGOPS SOSP accepted page contains no
links whatsoever. Yet a good share of those papers have been on arXiv for
months — search the title on Google Scholar and the first hit is that arXiv
page.

Scholar itself is not usable here: its robots.txt says Disallow /scholar, and a
plain request without browser fingerprinting comes back 403. Running that from
CI would get the runner blocked, and this is a public repository. Semantic
Scholar's /paper/search/match is the sanctioned way to the same data: no key
required, a documented contract, and the externalIds it returns carry the very
arXiv id Scholar displays.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from csconf import http
from csconf.models import Paper

MATCH_ENDPOINT = "https://api.semanticscholar.org/graph/v1/paper/search/match"
MATCH_FIELDS = "title,authors,externalIds,openAccessPdf"

URL_SOURCE = "semanticscholar"

# Misses have to be remembered too, or every month re-asks about the same
# papers. But not forever: papers often appear on arXiv months after the
# conference, so retry once a quarter.
MISS_RETRY_DAYS = 90

# Per-run ceiling. This step shares CI's 45-minute budget with the sync itself,
# and the anonymous Semantic Scholar quota is shared with every other caller.
# Stop when it is spent; the rest waits for next month.
DEFAULT_BUDGET = 400


@dataclass
class MatchRecord:
    title: str
    authors: Sequence[str]
    arxiv: Optional[str] = None
    doi: Optional[str] = None
    open_access_pdf: Optional[str] = None


def _surnames(names: Sequence[str]) -> set:
    return {n.split()[-1].lower() for n in names if n.split()}


def _normalized(title: str) -> str:
    """Reuse Paper's normalisation so cross-source title comparison lives in one place."""
    return Paper(title=title, authors=[], venue="", year=0).merge_key()


def choose_url(record: MatchRecord) -> Optional[str]:
    """The abs page beats the PDF: it has the abstract, every version, and the PDF."""
    if record.arxiv:
        return "https://arxiv.org/abs/{}".format(record.arxiv)
    if record.open_access_pdf:
        return record.open_access_pdf
    if record.doi:
        return "https://doi.org/{}".format(record.doi)
    return None


def is_confident(paper: Paper, record: MatchRecord) -> bool:
    """Accept on an identical title, or on agreeing authors — one or the other.

    Semantic Scholar matches fuzzily, so a different paper with a similar title
    comes back just as readily. Writing a wrong link into a public repository is
    worse than leaving the field empty: empty is visibly empty, while a wrong
    link looks perfectly fine.

    Requiring an identical title is too strict, though. SOSP 2026's "...with
    CrystalLLM" is on arXiv as "...with PrismLLM"; systems get renamed between
    submission and camera-ready all the time. The author list still agrees, and
    that is what catches this case.
    """
    if _normalized(record.title) == _normalized(paper.title):
        return True

    ours = _surnames([a.name for a in paper.authors])
    theirs = _surnames(record.authors)
    shared = len(ours & theirs)
    # Two shared surnames, because one collides too easily — Zhang, Kim and
    # Smith are everywhere. A single-author paper has no second name to check,
    # so one has to do.
    return shared >= 2 or (shared == 1 and len(ours) == 1)


def parse_match(payload: str) -> Optional[MatchRecord]:
    data = json.loads(payload).get("data") or []
    if not data:
        return None

    item = data[0]
    external = item.get("externalIds") or {}
    open_access = item.get("openAccessPdf") or {}
    return MatchRecord(
        title=item.get("title") or "",
        authors=[a.get("name", "") for a in item.get("authors") or []],
        arxiv=external.get("ArXiv"),
        doi=external.get("DOI"),
        open_access_pdf=open_access.get("url"),
    )


def match_url(title: str) -> str:
    return "{}?query={}&fields={}".format(
        MATCH_ENDPOINT, urllib.parse.quote(title), MATCH_FIELDS
    )


@dataclass
class Lookup:
    """The outcome of one lookup.

    conclusive separates "asked, and this paper is not there" from "never got
    to ask". Only the first is worth remembering: caching a rate-limited
    request as a miss would silence that paper for a whole quarter over a blip
    that lasted seconds.
    """

    url: Optional[str] = None
    conclusive: bool = True


def lookup(paper: Paper, fetcher) -> Lookup:
    """Look up one paper. Nothing here may fail the run — a missing link is
    just a missing link."""
    try:
        payload = fetcher.get(match_url(paper.title))
    except http.NotFound:
        # Semantic Scholar answers "no title match" with a 404. That is an
        # answer, not a fault.
        return Lookup(url=None, conclusive=True)
    except (http.RateLimited, http.HttpError) as exc:
        print("  lookup failed {}: {}".format(paper.title[:60], exc), file=sys.stderr)
        return Lookup(url=None, conclusive=False)
    except ValueError as exc:
        print("  lookup returned non-JSON {}: {}".format(paper.title[:60], exc), file=sys.stderr)
        return Lookup(url=None, conclusive=False)

    record = parse_match(payload)
    if record is None:
        return Lookup(url=None, conclusive=True)
    if not is_confident(paper, record):
        print(
            "  match rejected: {!r} -> {!r}".format(paper.title[:50], record.title[:50]),
            file=sys.stderr,
        )
        return Lookup(url=None, conclusive=True)
    return Lookup(url=choose_url(record), conclusive=True)


def _is_stale(checked: Optional[str], today: str) -> bool:
    if not checked:
        return True
    try:
        age = dt.date.fromisoformat(today) - dt.date.fromisoformat(checked)
    except ValueError:
        return True
    return age.days >= MISS_RETRY_DAYS


def enrich_papers(
    papers: Sequence[Paper],
    cache: Dict[str, Any],
    fetcher,
    today: str,
    budget: int = DEFAULT_BUDGET,
) -> Tuple[List[Paper], Dict[str, Any], Dict[str, Any]]:
    """Fill in urls for papers that lack one; returns (papers, cache, stats).

    The cache has to live on disk of its own: sync rewrites each JSON file in
    full every month, so the links filled in here are overwritten by the source
    data, and without a cache every month would re-ask the API about the same
    papers.
    """
    cache = dict(cache)
    stats = {
        "queried": 0,
        "found": 0,
        "cached": 0,
        "rejected": 0,
        "unavailable": 0,
        "skipped_recent_miss": 0,
        "budget_exhausted": False,
    }
    result: List[Paper] = []

    for paper in papers:
        if paper.url:
            # An official page from DBLP or the conference site always beats
            # something a third party matched to the title.
            result.append(paper)
            continue

        key = paper.merge_key()
        entry = cache.get(key)
        if entry and entry.get("url"):
            result.append(_with_url(paper, entry["url"], entry.get("source", URL_SOURCE)))
            stats["cached"] += 1
            continue
        if entry and not _is_stale(entry.get("checked"), today):
            stats["skipped_recent_miss"] += 1
            result.append(paper)
            continue

        if stats["queried"] >= budget:
            stats["budget_exhausted"] = True
            result.append(paper)
            continue

        stats["queried"] += 1
        outcome = lookup(paper, fetcher)
        if outcome.url:
            cache[key] = {"url": outcome.url, "source": URL_SOURCE, "checked": today}
            stats["found"] += 1
            result.append(_with_url(paper, outcome.url, URL_SOURCE))
            continue

        result.append(paper)
        if outcome.conclusive:
            cache[key] = {"url": None, "checked": today}
            stats["rejected"] += 1
        else:
            # Leave the cache alone so the next run asks again.
            stats["unavailable"] += 1

    return result, cache, stats


def _with_url(paper: Paper, url: str, source: str) -> Paper:
    from dataclasses import replace

    return replace(paper, url=url, url_source=source)


def build_session():
    """A requests session carrying identification and, if configured, a key.

    The anonymous rate limit is shared by every caller on the internet; a full
    run measurably sits at 429 for most of its length. A free key lifts that,
    but it stays optional so the repo still works for anyone who clones it.
    """
    import os

    import requests

    session = requests.Session()
    session.headers["User-Agent"] = (
        "csconf-papers/0.1 (+https://github.com/RealZST/csconf-papers)"
    )
    key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if key:
        session.headers["x-api-key"] = key
    return session
