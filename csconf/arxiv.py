"""The arXiv API (Atom) and the per-paper HTML author block.

Two measured facts shape this module. The API's submittedDate range filter is
unreliable (a year-long window returned 1 of Stoica's 60 papers), so callers
page through results sorted by submission date and stop locally. And arXiv
metadata almost never carries affiliations (1 of 150 sampled entries), so the
school lives only in the LaTeXML HTML rendering of the paper.
"""
from __future__ import annotations

import html as html_lib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional, Tuple
from urllib.parse import urlencode

API_URL = "https://export.arxiv.org/api/query"
HTML_URL = "https://arxiv.org/html/{}"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
OPENSEARCH_NS = "{http://a9.com/-/spec/opensearch/1.1/}"

_ID_FROM_URL = re.compile(r"arxiv\.org/abs/(.+?)(?:v\d+)?$")

# LaTeXML sometimes adds a layout class after the main one
# (`ltx_authors ltx_authors_1line`), so these match the main class as the first
# class followed by a quote or a space. A main class listed later is not found.
_AUTHORS_START = re.compile(r'class="ltx_authors["\s]')
_ABSTRACT_START = re.compile(r'class="ltx_abstract["\s]')
_SECTION_START = "<section"

# The block is cut right before the abstract or a section, which can leave a
# tag half-written at the end (e.g. `<div id="abstract1" `). A tag with no
# closing `>` must still be stripped, or its `<` leaks into the text.
_TAG = re.compile(r"<[^>]*(?:>|$)")


@dataclass
class ArxivEntry:
    arxiv_id: str
    title: str
    abstract: str
    authors: List[str]
    published: str  # YYYY-MM-DD of the first version
    primary_category: str


def search_url(name: str, start: int = 0, max_results: int = 100) -> str:
    query = {
        "search_query": 'au:"{}"'.format(name),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "start": start,
        "max_results": max_results,
    }
    return API_URL + "?" + urlencode(query)


def html_url(arxiv_id: str) -> str:
    return HTML_URL.format(arxiv_id)


def arxiv_id_from_url(url: str) -> str:
    match = _ID_FROM_URL.search(url.strip())
    if not match:
        raise ValueError("not an arXiv abs URL: {}".format(url))
    return match.group(1)


def _text(node) -> str:
    return " ".join((node.text or "").split()) if node is not None else ""


def parse_feed(xml_text: str) -> Tuple[List[ArxivEntry], int]:
    """Entries of one API page and the listing's opensearch:totalResults.

    Anything else raises ValueError. An API error arrives as a feed whose one
    entry has an api/errors id, which arxiv_id_from_url rejects.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError("not an Atom feed: {}".format(exc)) from exc
    entries = [_parse_entry(entry) for entry in root.findall(ATOM + "entry")]
    return entries, int(_text(root.find(OPENSEARCH_NS + "totalResults")))


def _parse_entry(entry: ET.Element) -> ArxivEntry:
    primary = entry.find(ARXIV_NS + "primary_category")
    return ArxivEntry(
        arxiv_id=arxiv_id_from_url(_text(entry.find(ATOM + "id"))),
        title=_text(entry.find(ATOM + "title")),
        abstract=_text(entry.find(ATOM + "summary")),
        authors=[_text(a.find(ATOM + "name")) for a in entry.findall(ATOM + "author")],
        published=_text(entry.find(ATOM + "published"))[:10],
        primary_category=primary.get("term", "") if primary is not None else "",
    )


def author_block(html_text: str) -> Optional[str]:
    """Plain text of the LaTeXML author block, or None when the page has none.

    The block runs from the ltx_authors div to the abstract, or to the first
    section when a paper has no abstract. Only this span is searched for a
    school, so an affiliation mentioned in the body (a cited lab, an
    acknowledgement) cannot count. With neither marker the block has no known
    end, so the page counts as having none.
    """
    found = _AUTHORS_START.search(html_text)
    end = _block_end(html_text, found.start()) if found else None
    if end is None:
        return None
    chunk = html_text[found.start():end]
    chunk = chunk.split(">", 1)[1] if ">" in chunk else chunk
    text = html_lib.unescape(_TAG.sub(" ", chunk))
    return " ".join(text.split()) or None


def _block_end(html_text: str, start: int) -> Optional[int]:
    abstract = _ABSTRACT_START.search(html_text, start)
    ends = [
        position
        for position in (
            abstract.start() if abstract else -1,
            html_text.find(_SECTION_START, start),
        )
        if position >= 0
    ]
    return min(ends, default=None)
