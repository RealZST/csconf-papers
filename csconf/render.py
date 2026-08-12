from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from csconf.models import Paper


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
        title = (
            "[{}]({})".format(paper.title, paper.url) if paper.url else paper.title
        )
        authors = ", ".join(a.name for a in paper.authors)
        lines.append("- {}".format(title))
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
