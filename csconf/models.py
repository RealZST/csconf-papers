from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# DBLP appends a four-digit suffix to tell apart different people who share a
# name: "Li Jiang 0002" is the second Li Jiang in DBLP and its pid is 45/4954-2.
# 3237 of the 15265 author entries here carry one (21.2%), and every single one
# of them also has a pid. The canonical form has to stay — stripping it before
# matching would merge two real people into one — but no reader should see it,
# and no consumer of this data should have to know the rule, so both forms ship.
_DBLP_DISAMBIGUATION = re.compile(r"\s+\d{4}$")

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


def display_name(name: str) -> str:
    """The name as a person should read it, without DBLP's homonym suffix."""
    return _DBLP_DISAMBIGUATION.sub("", name)


@dataclass
class Author:
    name: str
    pid: Optional[str] = None
    orcid: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        # display_name is derived on every write rather than stored on the
        # dataclass, so a stale value in an old file can never disagree with the
        # canonical name it comes from.
        return {
            "name": self.name,
            "display_name": display_name(self.name),
            "pid": self.pid,
            "orcid": self.orcid,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Author":
        return cls(name=data["name"], pid=data.get("pid"), orcid=data.get("orcid"))


@dataclass
class Paper:
    title: str
    authors: List[Author]
    venue: str
    year: int
    published_year: Optional[int] = None
    published_month: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    # Set when the link was not in the source data but matched in afterwards.
    # In a public dataset, "the official page" and "a preprint a third party
    # matched to this title" must not look identical.
    url_source: Optional[str] = None
    pdf_url: Optional[str] = None
    # The PDF URL is usually derived from url/doi. Where it came from decides
    # whether it needs verifying and whether it is actually free to read —
    # the publisher-doi ones need a subscription unless the paper is open.
    pdf_source: Optional[str] = None
    # The arXiv preprint of this paper, when one exists. Not the version of
    # record — it can differ from the camera-ready — but it is the one copy a
    # machine can always fetch, which is what makes it worth carrying.
    arxiv_id: Optional[str] = None
    pages: Optional[str] = None
    source: str = "dblp"
    dblp_paper_key: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "authors": [a.to_dict() for a in self.authors],
            "venue": self.venue,
            "year": self.year,
            "published_year": self.published_year,
            "published_month": self.published_month,
            "volume": self.volume,
            "issue": self.issue,
            "doi": self.doi,
            "url": self.url,
            "url_source": self.url_source,
            "pdf_url": self.pdf_url,
            "pdf_source": self.pdf_source,
            "arxiv_id": self.arxiv_id,
            "pages": self.pages,
            "source": self.source,
            "dblp_paper_key": self.dblp_paper_key,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Paper":
        """Restore from stored JSON so re-rendering never has to refetch DBLP."""
        return cls(
            title=data["title"],
            authors=[Author.from_dict(a) for a in data.get("authors", [])],
            venue=data["venue"],
            year=data["year"],
            published_year=data.get("published_year"),
            published_month=data.get("published_month"),
            volume=data.get("volume"),
            issue=data.get("issue"),
            doi=data.get("doi"),
            url=data.get("url"),
            url_source=data.get("url_source"),
            pdf_url=data.get("pdf_url"),
            pdf_source=data.get("pdf_source"),
            arxiv_id=data.get("arxiv_id"),
            pages=data.get("pages"),
            source=data.get("source", "dblp"),
            dblp_paper_key=data.get("dblp_paper_key"),
        )

    def merge_key(self) -> str:
        """Key for merging across sources.

        DBLP titles end in a period and site titles do not, and punctuation and
        whitespace differ freely, so compare normalised forms.
        """
        lowered = self.title.lower()
        return _SPACE.sub(" ", _PUNCT.sub(" ", lowered)).strip()
