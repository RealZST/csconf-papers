from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import List, Optional

from csconf.models import Author, Paper

DOI_PREFIX = "https://doi.org/"

# Non-paper records that journal volumes carry
_FRONT_MATTER = re.compile(r"^front matter\.?$", re.IGNORECASE)
# PACMMOD editorial titles come in three observed shapes: with a colon, with a
# comma after PACMMOD, and without a colon. The pattern has to tolerate all
# three — missing the second one previously led to the wrong conclusion that an
# issue had no editorial at all.
_PACMMOD_EDITORIAL = re.compile(r"PACMMOD,?\s*V\d+,\s*N\d+\s*\((?:SIGMOD|PODS)\)", re.IGNORECASE)

_RECORD_TAGS = ("inproceedings", "article")


def _child_text(element: ET.Element, tag: str) -> Optional[str]:
    child = element.find(tag)
    return child.text if child is not None else None


def _child_full_text(element: ET.Element, tag: str) -> Optional[str]:
    """Join every text node under a child element.

    DBLP titles contain typesetting tags such as <i>/<sub>/<sup>, and .text
    returns only the fragment before the first child tag — "B<sub>2</sub>Mark:
    ..." gets truncated to "B". Twelve of the 380 records in PACMMOD volume 3
    (3.2%) contain nested tags.
    """
    child = element.find(tag)
    return "".join(child.itertext()) if child is not None else None


def _clean_title(raw: Optional[str]) -> str:
    """DBLP titles all end in a period; drop it to match conference-site titles."""
    if not raw:
        return ""
    return raw.strip().rstrip(".").strip()


def is_non_paper(title: Optional[str]) -> bool:
    if not title:
        return True
    stripped = title.strip()
    return bool(_FRONT_MATTER.match(stripped) or _PACMMOD_EDITORIAL.search(stripped))


def count_proceedings_entries(xml_text: str) -> int:
    root = ET.fromstring(xml_text)
    return sum(1 for element in root.iter() if element.tag == "proceedings")


def _parse_authors(element: ET.Element) -> List[Author]:
    return [
        Author(name=(a.text or "").strip(), pid=a.get("pid"), orcid=a.get("orcid"))
        for a in element.findall("author")
    ]


def _parse_int(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def parse_toc(xml_text: str, venue: str, year: int) -> List[Paper]:
    """Parse one DBLP venue TOC XML document into a list of papers.

    <proceedings> (conference front matter) falls out naturally by not being in
    _RECORD_TAGS; journal front matter and editorials are removed by
    is_non_paper.
    """
    root = ET.fromstring(xml_text)
    papers: List[Paper] = []

    for element in root.iter():
        if element.tag not in _RECORD_TAGS:
            continue

        title = _clean_title(_child_full_text(element, "title"))
        if is_non_paper(title):
            continue

        ee = _child_text(element, "ee")
        doi = ee[len(DOI_PREFIX):] if ee and ee.startswith(DOI_PREFIX) else None

        papers.append(
            Paper(
                title=title,
                authors=_parse_authors(element),
                venue=venue,
                year=year,
                published_year=_parse_int(_child_text(element, "year")),
                published_month=_child_text(element, "month"),
                volume=_child_text(element, "volume"),
                issue=_child_text(element, "number"),
                doi=doi,
                url=ee,
                pages=_child_text(element, "pages"),
                source="dblp",
                dblp_paper_key=element.get("key"),
            )
        )

    return papers
