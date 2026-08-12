from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from csconf import fallback, http, render, store, venues as venues_mod
from csconf.dblp import parse_toc
from csconf.models import Paper
from csconf.rounds import filter_by_rounds


class MappingDrift(Exception):
    """A venue-year marked `indexed` came back empty — usually a changed DBLP key."""


@dataclass
class SyncResult:
    venue: str
    year: int
    papers: List[Paper]
    note: Optional[str]
    source_keys: List[str]

    @property
    def paper_count(self) -> int:
        return len(self.papers)


def _note_for(config: Dict[str, Any], year: int, volume: Optional[int]) -> Optional[str]:
    template = config.get("note_template")
    if not template:
        return None
    return template.format(vol=volume, year=year)


def merge_sources(
    web_papers: List[Paper], dblp_papers: List[Paper]
) -> List[Paper]:
    """DBLP wins. A web record for the same paper is replaced, not appended."""
    merged = {p.merge_key(): p for p in web_papers}
    for paper in dblp_papers:
        merged[paper.merge_key()] = paper
    return list(merged.values())


def _fetch_fallback(
    config: Dict[str, Any], venue: str, year: int, fetcher
) -> List[Paper]:
    """Scrape the conference site while DBLP has not indexed the edition yet.

    A changed page structure or a missing page must not take the whole sync
    down: this is a stopgap, so a failure just means no data and an em dash.
    """
    url = config["fallback_url"].format(year=year, yy="{:02d}".format(year % 100))
    try:
        html = fetcher.get(url)
    except (http.HttpError, http.RateLimited) as exc:
        # Say so. Returning an empty list silently leaves only "0 papers" in
        # the log, which cannot be told apart from "this edition is not out
        # yet" — and USENIX does start refusing after repeated requests. The
        # two cases call for completely different responses.
        print("  fallback {} {} failed: {}".format(venue, year, exc), file=sys.stderr)
        return []

    papers = fallback.parse_for(venue, html, year)
    if not papers:
        print(
            "  fallback {} {} fetched the page but parsed 0 papers; the site "
            "structure may have changed: {}".format(
                venue, year, url
            ),
            file=sys.stderr,
        )
    return papers


def sync_venue_year(
    root: Path,
    venues: Dict[str, Any],
    venue: str,
    year: int,
    fetcher,
    updated: str,
    allow_shrink: bool = False,
) -> SyncResult:
    config = venues[venue]

    def volume_lookup(index_key: str, lookup_year: int) -> List[int]:
        html = fetcher.get(http.index_url(index_key))
        slug = index_key.rsplit("/", 1)[-1]
        return venues_mod.discover_volumes(html, slug, lookup_year)

    fetches = venues_mod.expand(venues, venue, year, volume_lookup=volume_lookup)

    papers: List[Paper] = []
    note: Optional[str] = None
    for fetch in fetches:
        try:
            xml_text = fetcher.get(http.toc_url(fetch.toc_key))
        except http.NotFound:
            # The TOC does not exist yet. For a pending venue that is normal
            # (the conference has happened, DBLP has not caught up). For an
            # indexed one it falls through to MappingDrift below, as intended.
            continue
        parsed = parse_toc(xml_text, venue=venue, year=year)

        if config["type"] == "journal_rounds":
            # Matched on (volume, issue) taken from the papers themselves, so
            # the caller's volume is not needed here.
            parsed = filter_by_rounds(parsed, rounds=config["rounds"][year])
        if config["type"] == "journal_volume":
            note = _note_for(config, year, fetch.volume)

        papers.extend(parsed)

    source_keys = [f.toc_key for f in fetches]
    status = venues_mod.status_of(venues, venue, year)

    if not papers and status == "pending" and config.get("fallback_url"):
        # The conference is over and the site has published the list, but DBLP
        # has not indexed it. Use the site for now; DBLP records take over once
        # they appear (merge_sources gives DBLP priority).
        papers = merge_sources(
            web_papers=_fetch_fallback(config, venue, year, fetcher),
            dblp_papers=papers,
        )

    if not papers:
        # Indexed but empty means the DBLP key changed. That edition would
        # silently vanish, so this has to be loud.
        if status == "indexed":
            raise MappingDrift(
                "{} {} is marked indexed but returned 0 papers; check the TOC "
                "key in venues.yaml".format(
                    venue, year
                )
            )
        # At zero papers, pending (not indexed yet) and partial (indexed but
        # nothing there yet) mean the same thing: the data does not exist.
        # Writing the file would produce a 0-paper JSON, and the README would
        # render [0](papers/2026/OSDI.md) — turning "not yet" into "genuinely
        # none" and destroying the em-dash-versus-0 distinction. Write nothing.
        return SyncResult(
            venue=venue, year=year, papers=[], note=None, source_keys=source_keys
        )

    store.write_venue_year(
        root=root, venue=venue, year=year, papers=papers,
        source_keys=source_keys, note=note, updated=updated, allow_shrink=allow_shrink,
    )

    markdown = render.render_venue_year(venue, year, papers, note, updated)
    md_path = Path(root) / "papers" / str(year) / "{}.md".format(venue)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown, encoding="utf-8")

    return SyncResult(
        venue=venue, year=year, papers=papers, note=note, source_keys=source_keys
    )
