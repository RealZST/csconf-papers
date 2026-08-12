from __future__ import annotations

import re
from html import unescape
from typing import Callable, Dict, List, Optional
from urllib.parse import urljoin

from csconf.dblp import _clean_title
from csconf.models import Author, Paper

# Each USENIX paper is an <article>, but speaker blocks are <article> too and
# the keynote block swallows its own closing tag through nesting. Split on the
# opening tag rather than trying to match closing ones.
_ARTICLE_SPLIT = re.compile(r"<article\b")
# The hrefs on the page are site-relative (/conference/osdi26/presentation/...)
# and have to be absolute in the JSON, or the Markdown links do not resolve.
_USENIX_BASE = "https://www.usenix.org/"
_USENIX_HEADING = re.compile(
    r"<h2>\s*<a\s+href=\"([^\"]*)\"[^>]*>(.*?)</a>\s*</h2>", re.DOTALL
)
_USENIX_AUTHORS = re.compile(
    r"field-name-field-paper-people-text.*?<p>(.*?)</p>", re.DOTALL
)

_SIGOPS_ITEM = re.compile(r"<li\b[^>]*>(.*?)</li>", re.DOTALL)
_SIGOPS_TITLE = re.compile(r"<b>(.*?)</b>", re.DOTALL)
_SIGOPS_AUTHORS = re.compile(r"<em>(.*?)</em>", re.DOTALL)

_EM_BLOCK = re.compile(r"<em\b[^>]*>.*?</em>", re.DOTALL)
_PAREN_GROUP = re.compile(r"\([^()]*\)")
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")

# Commas, semicolons and a standalone "and" all separate authors. An Oxford
# comma (", and ") yields an empty piece, which the caller drops.
_NAME_SEPARATOR = re.compile(r"\s*(?:,|;|\band\b)\s*")


def _text_of(fragment: str) -> str:
    """Strip tags, decode entities, normalise whitespace.

    Decoding is not optional: merge_key only lowercases and strips punctuation,
    so it does not know &amp;. Skipping this step would keep a paper's web
    record from matching the DBLP record that shows up later.
    """
    return _SPACE.sub(" ", unescape(_TAG.sub("", fragment))).strip()


def _strip_affiliations(text: str) -> str:
    """Strip inline affiliations, repeatedly, until no parentheses are left.

    _PAREN_GROUP only matches the innermost group (the pattern excludes
    parentheses), so nested affiliations need several passes. SOSP 2026 really
    contains "Ming-Chang Yang (The Chinese University of Hong Kong (CUHK))" and
    "Ke Zhou (Wuhan National Laboratory for Optoelectronics (WNLO) of Huazhong
    University of Science and Technology (HUST))". A single pass leaves shards
    like "(The Chinese University of Hong Kong ," which then split on the comma
    into authors who do not exist.
    """
    previous = None
    while previous != text:
        previous = text
        text = _PAREN_GROUP.sub(",", text)
    return text


def _split_names(text: str) -> List[Author]:
    return [
        Author(name=piece)
        for piece in (p.strip() for p in _NAME_SEPARATOR.split(text))
        if piece
    ]


def _make_paper(
    title: str,
    authors: List[Author],
    venue: str,
    year: int,
    url: Optional[str] = None,
) -> Paper:
    return Paper(
        title=title,
        authors=authors,
        venue=venue,
        year=year,
        doi=None,
        url=url,
        pages=None,
        source="{}-web".format(venue.lower()),
        dblp_paper_key=None,
    )


def parse_usenix_sessions(html: str, venue: str, year: int) -> List[Paper]:
    """Parse a USENIX technical-sessions page.

    Keynote and speaker blocks share the same <article> structure, so they are
    told apart by the /presentation/<slug> slug: a real paper's slug is an
    author name, the keynote's is literally "keynote".
    """
    papers: List[Paper] = []

    for chunk in _ARTICLE_SPLIT.split(html):
        heading = _USENIX_HEADING.search(chunk)
        if heading is None:
            continue

        href, raw_title = heading.group(1), heading.group(2)
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        if "/presentation/" not in href or slug == "keynote":
            continue

        title = _clean_title(_text_of(raw_title))
        if not title:
            continue

        authors: List[Author] = []
        match = _USENIX_AUTHORS.search(chunk)
        if match:
            # Affiliations sit inside <em>; drop those blocks and what remains
            # is a plain sequence of names.
            authors = _split_names(_text_of(_EM_BLOCK.sub(",", match.group(1))))

        papers.append(
            _make_paper(title, authors, venue, year, url=urljoin(_USENIX_BASE, href))
        )

    return papers


def parse_sigops_accepted(html: str, venue: str, year: int) -> List[Paper]:
    """Parse a SIGOPS accepted-papers page (<li> under <ul class="paperlist">)."""
    papers: List[Paper] = []

    for item in _SIGOPS_ITEM.findall(html):
        title_match = _SIGOPS_TITLE.search(item)
        if title_match is None:
            continue

        title = _clean_title(_text_of(title_match.group(1)))
        if not title:
            continue

        authors: List[Author] = []
        authors_match = _SIGOPS_AUTHORS.search(item)
        if authors_match:
            # Affiliations are inline and contain commas of their own
            # ("(University of California, Los Angeles)"), so parentheses have
            # to come off before splitting or the split invents authors.
            text = _text_of(authors_match.group(1))
            authors = _split_names(_strip_affiliations(text))

        papers.append(_make_paper(title, authors, venue, year))

    return papers


PARSERS: Dict[str, Callable[..., List[Paper]]] = {
    "OSDI": parse_usenix_sessions,
    "SOSP": parse_sigops_accepted,
}


def parse_for(venue: str, html: str, year: int) -> List[Paper]:
    parser = PARSERS.get(venue)
    if parser is None:
        return []
    return parser(html, venue=venue, year=year)
