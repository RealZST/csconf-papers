"""Decide whether an arXiv paper under a tracked name is that researcher's.

arXiv metadata carries no affiliations, so a name alone cannot tell a tracked
researcher from a homonym. The rules below add evidence only where the name is
shared; their thresholds were set from a measurement taken on 2026-09-28.

A paper is a candidate when its primary category is cs.*, it has at most 30
authors, and the tracked name is in its author list. The author cap drops the
huge physics-style collaborations.

Each researcher's match mode (see researchers.yaml) sets what else is needed:

- name: nothing; the name is unique among DBLP authors.
- school: the HTML author block names one of the researcher's schools.
- strict: the school AND the coauthor rule, because a homonym at the same
  school passes the school check.

Not every paper has an HTML rendering. Without an author block, both school
and strict fall back to the coauthor rule alone rather than dropping the paper.

The coauthor rule accepts a paper when DBLP already lists this arXiv id for the
person; or at least two of its other authors are known DBLP coauthors; or
exactly one is and they share at least two papers. A single one-off coauthor is
too weak a link on its own.

Known limit: the school is matched anywhere in the author block, not on the
tracked person's own line, because LaTeXML output often does not pair names
with affiliations. So in school mode a namesake who writes with an HKU
coauthor is accepted as Chuan Wu. That is accepted because school mode is only
used where the name's other DBLP holders are at other schools.
"""
from __future__ import annotations

import re
from typing import Optional

from csconf.arxiv import ArxivEntry
from csconf.dblp import PersonProfile, norm_name
from csconf.models import Researcher

MAX_AUTHORS = 30


def author_position(entry: ArxivEntry, name: str) -> Optional[int]:
    """1-based position of the name in the author list, or None."""
    target = norm_name(name)
    for index, author in enumerate(entry.authors):
        if norm_name(author) == target:
            return index + 1
    return None


def is_candidate(entry: ArxivEntry, researcher: Researcher) -> bool:
    return (
        entry.primary_category.startswith("cs.")
        and len(entry.authors) <= MAX_AUTHORS
        and author_position(entry, researcher.name) is not None
    )


def _coauthor_linked(entry: ArxivEntry, researcher: Researcher, profile: PersonProfile) -> bool:
    if entry.arxiv_id in profile.arxiv_ids:
        return True
    others = {norm_name(a) for a in entry.authors} - {norm_name(researcher.name)}
    hits = [profile.coauthors[n] for n in others if n in profile.coauthors]
    return len(hits) >= 2 or (len(hits) == 1 and hits[0] >= 2)


def decide(
    entry: ArxivEntry, researcher: Researcher, block: Optional[str],
    profile: Optional[PersonProfile],
) -> Optional[str]:
    """The attribution label for a candidate, or None to reject it."""
    if researcher.match == "name":
        return "name"
    if block is None:
        return "coauthor" if _coauthor_linked(entry, researcher, profile) else None
    if not any(re.search(pattern, block) for pattern in researcher.schools):
        return None
    if researcher.match == "school":
        return "school"
    return "school+coauthor" if _coauthor_linked(entry, researcher, profile) else None
