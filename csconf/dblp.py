from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import List, Optional

from csconf.models import Author, Paper

DOI_PREFIX = "https://doi.org/"

# 期刊类需要剔除的非论文条目
_FRONT_MATTER = re.compile(r"^front matter\.?$", re.IGNORECASE)
# PACMMOD editorial 标题格式在实测中有三种变体：带冒号、PACMMOD 后带逗号、缺冒号。
# 正则必须容忍这些差异——曾因未覆盖第二种而误判某期「没有 editorial」。
_PACMMOD_EDITORIAL = re.compile(r"PACMMOD,?\s*V\d+,\s*N\d+\s*\((?:SIGMOD|PODS)\)", re.IGNORECASE)

_RECORD_TAGS = ("inproceedings", "article")


def _child_text(element: ET.Element, tag: str) -> Optional[str]:
    child = element.find(tag)
    return child.text if child is not None else None


def _child_full_text(element: ET.Element, tag: str) -> Optional[str]:
    """拼接子元素下的全部文本节点。

    DBLP 的标题里会出现 <i>/<sub>/<sup> 等排版标签，此时 .text 只返回
    第一个子标签之前的片段——"B<sub>2</sub>Mark: ..." 会被截成 "B"。
    实测 PACMMOD vol 3 的 380 条记录中有 12 条（3.2%）含嵌套标签。
    """
    child = element.find(tag)
    return "".join(child.itertext()) if child is not None else None


def _clean_title(raw: Optional[str]) -> str:
    """DBLP 标题统一以句点结尾，去掉以便与官网标题一致。"""
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
    """把一个 DBLP venue TOC XML 解析成论文列表。

    <proceedings>（会议前言）因不在 _RECORD_TAGS 中而自然排除；
    期刊类的 Front Matter 与 editorial 由 is_non_paper 剔除。
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
