from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


@dataclass
class Author:
    name: str
    pid: Optional[str] = None
    orcid: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "pid": self.pid, "orcid": self.orcid}


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
            "pages": self.pages,
            "source": self.source,
            "dblp_paper_key": self.dblp_paper_key,
        }

    def merge_key(self) -> str:
        """跨数据源合并用的键。DBLP 标题以句点结尾而官网标题不带，
        标点与空白差异也常见，因此归一化后再比。"""
        lowered = self.title.lower()
        return _SPACE.sub(" ", _PUNCT.sub(" ", lowered)).strip()
