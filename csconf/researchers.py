"""Tracked researchers and their recent arXiv papers.

The list lives in researchers.yaml at the repo root. Each person is matched to
arXiv papers by name, and where the name is shared, by the school in the
paper's HTML author block (see attribution.py for why metadata is not enough).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, NamedTuple, Optional

import yaml

from csconf import arxiv, dblp
from csconf.arxiv import ArxivEntry
from csconf.attribution import author_position, decide, is_candidate
from csconf.http import NotFound
from csconf.models import MATCH_MODES, Researcher

# The page shows about three months. The extra weeks cover one failed run of
# the every-other-week job: the next run still reaches back over its window.
LOOKBACK_DAYS = 120


def load_researchers(path: str) -> List[Researcher]:
    with open(path, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    researchers = []
    for item in raw["researchers"]:
        _check(item)
        # The slug keys data/researchers.json, so two people cannot share one.
        if any(r.slug == item["slug"] for r in researchers):
            raise ValueError("{}: duplicate slug".format(item["slug"]))
        researchers.append(Researcher(
            slug=item["slug"], name=item["name"], dblp_pid=item["dblp_pid"],
            affiliation=item["affiliation"], known_for=item.get("known_for") or "",
            match=item["match"], schools=list(item.get("schools") or []),
        ))
    return researchers


def _check(item: Dict[str, Any]) -> None:
    """Reject an entry here, at load time: otherwise a typo surfaces only
    minutes into the network run, or worse, never, as silent misattribution."""
    slug = item["slug"]
    if item["match"] not in MATCH_MODES:
        raise ValueError("{}: unknown match mode {!r}".format(slug, item["match"]))
    schools = item.get("schools") or []
    # A bare string would be split into one-character patterns that match anything.
    if not isinstance(schools, list):
        raise ValueError("{}: schools must be a list of patterns".format(slug))
    if item["match"] != "name" and not schools:
        raise ValueError(
            "{}: match={} needs at least one school pattern".format(slug, item["match"])
        )
    for pattern in schools:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(
                "{}: school pattern {!r} does not compile: {}".format(slug, pattern, exc)
            ) from exc


def collect(
    researcher: Researcher, fetcher, since: str, page_size: int = 100, max_pages: int = 5
) -> List[ArxivEntry]:
    """The researcher's arXiv entries first submitted on or after `since`.

    Results come newest first, so paging stops at the first page that reaches
    past the cutoff. A listing cut short raises ValueError instead of returning
    what it has: a silently truncated list would look like a complete one.
    """
    kept: List[ArxivEntry] = []
    start, total = 0, None
    for _ in range(max_pages):
        entries, page_total = arxiv.parse_feed(
            fetcher.get(arxiv.search_url(researcher.name, start, page_size))
        )
        # Fixed by the first page, so a later page misreporting it cannot end
        # the listing early.
        # A first page under-reporting it still can; accepted, since the next
        # run fetches the whole lookback window again.
        total = page_total if total is None else total
        if not entries:
            # arXiv sporadically serves an empty page mid-listing; taking it
            # for the end would drop every paper after it.
            if start < total:
                raise ValueError("{}: empty arXiv page at {} of {}".format(
                    researcher.slug, start, total))
            return kept
        kept += [e for e in entries if e.published >= since]
        if entries[-1].published < since or start + len(entries) >= total:
            return kept
        start += len(entries)
    raise ValueError("{}: more than {} arXiv pages since {}".format(
        researcher.slug, max_pages, since))


class Synced(NamedTuple):
    papers: List[Dict[str, Any]]
    # Counted so the run log shows how many papers the attribution judged, and
    # how many of those only by the weaker coauthor rule.
    candidates: int
    without_html: int  # no HTML page, or no author block in it


def sync_researcher(researcher: Researcher, fetcher, since: str) -> Synced:
    """The researcher's papers found this run, as data/researchers.json records.

    Any fetch failure other than a missing HTML page propagates, so the whole
    researcher fails and keeps their previous record: better than quietly
    judging papers by a weaker rule than their match mode asks for.
    """
    profile: Optional[dblp.PersonProfile] = None
    records = []
    candidates = without_html = 0
    for entry in collect(researcher, fetcher, since):
        if not is_candidate(entry, researcher):
            continue
        candidates += 1
        block = None
        if researcher.match != "name":
            block = _author_block(fetcher, entry.arxiv_id)
            without_html += block is None
            if profile is None and (researcher.match == "strict" or block is None):
                profile = dblp.parse_person_profile(
                    fetcher.get(dblp.person_papers_query_url(researcher.dblp_pid)),
                    researcher.dblp_pid,
                )
        label = decide(entry, researcher, block, profile)
        if label:
            records.append({
                "arxiv_id": entry.arxiv_id,
                "title": entry.title,
                "abstract": entry.abstract,
                "authors": entry.authors,
                "published": entry.published,
                "primary_category": entry.primary_category,
                "position": author_position(entry, researcher.name),
                "attribution": label,
            })
    return Synced(records, candidates, without_html)


def _author_block(fetcher, arxiv_id: str) -> Optional[str]:
    try:
        return arxiv.author_block(fetcher.get(arxiv.html_url(arxiv_id)))
    except NotFound:
        # Not every paper gets an HTML rendering; decide() then falls back to
        # the coauthor rule.
        return None


def merge_feed(
    previous: Optional[Dict[str, Any]],
    researchers: List[Researcher],
    fresh: Dict[str, List[Dict[str, Any]]],
    generated: str,
) -> Dict[str, Any]:
    """The new data/researchers.json from the previous one and this run.

    A rolling window, not an archive: paper-viewer keeps every paper in its own
    database, so the file only has to cover LOOKBACK_DAYS. `fresh` holds only
    the researchers that synced, and they get exactly this run's papers; one
    that failed keeps its previous papers. One that has never synced is left
    out, so no reader mistakes it for someone with no recent papers. A
    researcher gone from researchers.yaml goes from the file, and everything
    but the papers comes from the yaml.
    """
    old = {item["slug"]: item["papers"] for item in (previous or {}).get("researchers", [])}
    items = []
    for researcher in researchers:
        papers = fresh.get(researcher.slug, old.get(researcher.slug))
        if papers is None:
            continue
        items.append({
            "slug": researcher.slug,
            "name": researcher.name,
            "affiliation": researcher.affiliation,
            "known_for": researcher.known_for,
            "papers": sorted(
                papers, key=lambda p: (p["published"], p["arxiv_id"]), reverse=True
            ),
        })
    return {"schema": 1, "generated": generated, "researchers": items}
