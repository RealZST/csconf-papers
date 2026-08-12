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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Paper":
        """从已存 JSON 还原，使重新渲染不必回头再抓一遍 DBLP。"""
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
            pages=data.get("pages"),
            source=data.get("source", "dblp"),
            dblp_paper_key=data.get("dblp_paper_key"),
        )

    def merge_key(self) -> str:
        """跨数据源合并用的键。DBLP 标题以句点结尾而官网标题不带，
        标点与空白差异也常见，因此归一化后再比。"""
        lowered = self.title.lower()
        return _SPACE.sub(" ", _PUNCT.sub(" ", lowered)).strip()
