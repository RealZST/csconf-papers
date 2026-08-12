"""Find a PDF URL for each paper.

Most of them need no API at all — the address is already inside the url or doi
we hold:

- PVLDB's ee points straight at a PDF
- a USENIX presentation URL carries the conference tag and the slug, which is
  enough to build the PDF address; a spot check of 12 across OSDI 25/26, NSDI 25
  and ATC 25 returned 200 application/pdf every time
- an ACM DOI builds a dl.acm.org PDF address directly

A derived address is still a guess, so it gets one HEAD check before it goes
into a public listing, and the result is cached so each URL is checked once.
The ACM path is not checked: its URL scheme is guaranteed by the publisher, and
dl.acm.org blocks automated requests anyway. Whether it actually downloads
depends on the paper being open access, which is what the source marker is for
— it must not be dressed up as free full text.
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Callable, Dict, Optional, Tuple

from csconf.models import Paper

_USENIX_PRESENTATION = re.compile(
    r"^https://www\.usenix\.org/conference/([^/]+)/presentation/(.+?)/?$"
)
_ARXIV_ABS = re.compile(r"^https://arxiv\.org/abs/(.+?)(?:v\d+)?/?$")

# Only ACM DOIs build a PDF address. Other publishers use different paths, and
# applying this one blindly just produces a link that 404s — worse than none.
_ACM_DOI_PREFIX = "10.1145/"

SCHOLAR_SEARCH = "https://scholar.google.com/scholar?q={}"

# HEAD checks share the CI run's clock with the sync itself. Whatever is left
# over gets picked up next month; the cache means each URL is only ever checked
# once, so the backlog drains quickly.
DEFAULT_VERIFY_BUDGET = 800

# Sources that need a HEAD check: the derived ones. Addresses we were handed
# outright do not.
_DERIVED = {"usenix-derived", "arxiv-derived"}


def looks_like_pdf(url: str) -> bool:
    path = urllib.parse.urlparse(url).path
    return path.lower().endswith(".pdf") or "/doi/pdf/" in path


def needs_verification(source: Optional[str]) -> bool:
    return source in _DERIVED


def scholar_search_url(title: str) -> str:
    """Build a Scholar search URL. Nothing is fetched.

    Scholar's robots.txt says Disallow /scholar and a direct request returns
    403. Building a search link for a person to click requires fetching
    nothing — and even for a paper that turns up nowhere else, that address
    takes a reader where they need to go.
    """
    return SCHOLAR_SEARCH.format(urllib.parse.quote(title))


def derive(paper: Paper) -> Tuple[Optional[str], Optional[str]]:
    """Return (pdf url, source marker), or (None, None) if nothing can be derived."""
    url = paper.url or ""

    if url and looks_like_pdf(url):
        return url, "source"

    usenix = _USENIX_PRESENTATION.match(url)
    if usenix:
        conference, slug = usenix.group(1), usenix.group(2)
        return (
            "https://www.usenix.org/system/files/{}-{}.pdf".format(conference, slug),
            "usenix-derived",
        )

    arxiv = _ARXIV_ABS.match(url)
    if arxiv:
        return "https://arxiv.org/pdf/{}".format(arxiv.group(1)), "arxiv-derived"

    if paper.doi and paper.doi.startswith(_ACM_DOI_PREFIX):
        return "https://dl.acm.org/doi/pdf/{}".format(paper.doi), "publisher-doi"

    return None, None


def fill_pdfs(
    papers,
    cache: Dict[str, bool],
    head: Callable[[str], bool],
    budget: int = DEFAULT_VERIFY_BUDGET,
):
    """Attach a PDF URL to every paper we can derive one for.

    Only guessed URLs cost a request. PVLDB already points at a PDF and the ACM
    path is fixed by the publisher's own URL scheme, so those cost nothing and
    keep working after the verification budget is spent.
    """
    from dataclasses import replace

    stats = {"filled": 0, "checked": 0, "unverified": 0, "budget_exhausted": False}
    result = []

    for paper in papers:
        if paper.pdf_url:
            result.append(paper)
            continue

        url, source = derive(paper)
        if url is None:
            result.append(paper)
            continue

        if needs_verification(source):
            if url not in cache and stats["checked"] >= budget:
                stats["budget_exhausted"] = True
                result.append(paper)
                continue
            was_cached = url in cache
            ok, cache = verify(url, head, cache)
            if not was_cached:
                stats["checked"] += 1
            if not ok:
                # A guessed URL that does not serve a PDF is worse than no link:
                # it looks exactly like a working one until someone clicks it.
                stats["unverified"] += 1
                result.append(paper)
                continue

        result.append(replace(paper, pdf_url=url, pdf_source=source))
        stats["filled"] += 1

    return result, cache, stats


def verify(
    url: str, head: Callable[[str], bool], cache: Dict[str, bool]
) -> Tuple[bool, Dict[str, bool]]:
    """Check once and remember the answer.

    Re-checking two thousand papers every month is pure waste, and usenix.org
    does start blocking after repeated requests.
    """
    if url in cache:
        return cache[url], cache

    ok = head(url)
    cache = dict(cache)
    cache[url] = ok
    return ok, cache
