from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

from csconf.models import Paper

# DBLP 给重名作者加四位消歧后缀，如 "Song Yu 0004"。实测 12518 个作者条目里
# 22.8% 带后缀，在给人读的列表里纯属噪音。JSON 保留 DBLP 规范形式，且带后缀的
# 条目全部都有 pid，因此显示时剥掉不丢任何身份信息。
_DBLP_DISAMBIGUATION = re.compile(r"\s+\d{4}$")


def display_name(name: str) -> str:
    return _DBLP_DISAMBIGUATION.sub("", name)


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
        authors = ", ".join(display_name(a.name) for a in paper.authors)
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
