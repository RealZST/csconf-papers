from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from csconf import pdf as pdf_mod
from csconf.models import Paper

# DBLP disambiguates identical names with a four-digit suffix, as in "Song Yu
# 0004". It is on 22.8% of the 12518 author entries here and is pure noise in a
# list meant for people. The JSON keeps DBLP's canonical form, and every
# suffixed entry also carries a pid, so dropping it loses no identity.
_DBLP_DISAMBIGUATION = re.compile(r"\s+\d{4}$")


def display_name(name: str) -> str:
    return _DBLP_DISAMBIGUATION.sub("", name)


def _render_links(paper: Paper) -> str:
    """Title carries the main link, followed by a provenance marker and the PDF.

    With no source link at all, fall back to a Scholar search URL: even for a
    paper that turns up nowhere else, that address takes a reader where they
    need to go. It is constructed, never fetched.
    """
    url = paper.url or pdf_mod.scholar_search_url(paper.title)
    parts = ["[{}]({})".format(paper.title, url)]

    # For links that are not the publisher's own page, show where they land so
    # readers can judge for themselves. Looking identical to an official DBLP
    # link is the dishonest option.
    if paper.url_source or not paper.url:
        parts.append(urlparse(url).netloc)

    if paper.pdf_url:
        # Anyone can construct a dl.acm.org URL, but a paper that is not open
        # access asks for a subscription behind it. Labelling that the same as
        # free full text baits the click.
        label = "PDF (ACM)" if paper.pdf_source == "publisher-doi" else "PDF"
        parts.append("[{}]({})".format(label, paper.pdf_url))

    return " · ".join(parts)


def render_venue_year(
    venue: str,
    year: int,
    papers: Sequence[Paper],
    note: Optional[str],
    updated: str,
) -> str:
    lines = ["# {} {}".format(venue, year), ""]
    lines.append("{} papers · updated {}".format(len(papers), updated))
    lines.append("")
    if note:
        lines.append("> {}".format(note))
        lines.append("")

    for paper in sorted(papers, key=lambda p: p.title.lower()):
        lines.append("- {}".format(_render_links(paper)))
        authors = ", ".join(display_name(a.name) for a in paper.authors)
        if authors:
            lines.append("  {}".format(authors))

    return "\n".join(lines) + "\n"


def render_readme(
    venues: Sequence[str],
    years: Sequence[int],
    counts: Dict[Tuple[str, int], int],
    updated: str,
) -> str:
    lines = [
        "# csconf-papers",
        "",
        "Accepted paper lists for top systems and database conferences, "
        "generated from DBLP.",
        "",
        "Data lives in `data/{year}/{VENUE}.json`; "
        "human-readable listings in `papers/{year}/{VENUE}.md`.",
        "",
        "Paper links come from DBLP where available. For editions DBLP has not "
        "indexed yet, the list is scraped from the conference site — which "
        "carries no links — and missing links are matched by title against "
        "Semantic Scholar, usually resolving to an arXiv preprint. Those are "
        "marked with their host in the listings and with `url_source` in the JSON. "
        "A paper with no link anywhere falls back to a Google Scholar search URL.",
        "",
        "PDF links are derived from the link each paper already has: PVLDB "
        "points at a PDF directly, a USENIX presentation URL yields the file "
        "under `/system/files/` (checked with a HEAD request before it is "
        "published), and an ACM DOI builds a `dl.acm.org` address. The last "
        "kind is labelled `PDF (ACM)` because it needs a subscription unless "
        "the paper is open access.",
        "",
        "Last updated: {}".format(updated),
        "",
        "| Year | " + " | ".join(venues) + " |",
        "|---" * (len(venues) + 1) + "|",
    ]

    for year in years:
        cells: List[str] = []
        for venue in venues:
            count = counts.get((venue, year))
            if count is None:
                cells.append("—")
            else:
                cells.append("[{}](papers/{}/{}.md)".format(count, year, venue))
        lines.append("| {} | ".format(year) + " | ".join(cells) + " |")

    lines.append("")
    return "\n".join(lines) + "\n"
