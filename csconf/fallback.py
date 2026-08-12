from __future__ import annotations

import re
from html import unescape
from typing import Callable, Dict, List, Optional
from urllib.parse import urljoin

from csconf.dblp import _clean_title
from csconf.models import Author, Paper

# USENIX 的每篇论文是一个 <article>，但页面里还嵌着 speaker 的 <article>，
# 且 keynote 那块的闭合标签被嵌套吃掉了——因此按开标签切块而不是配对闭合。
_ARTICLE_SPLIT = re.compile(r"<article\b")
# 页面里的 href 是站内相对路径（/conference/osdi26/presentation/...），
# 存进 JSON 得补成绝对地址，否则 Markdown 里的链接点不开。
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

# 逗号、分号与独立的 "and" 都是作者分隔符。Oxford comma（", and "）会切出
# 一个空片段，由调用方丢弃。
_NAME_SEPARATOR = re.compile(r"\s*(?:,|;|\band\b)\s*")


def _text_of(fragment: str) -> str:
    """去标签 → 解实体 → 归一空白。

    解实体必不可少：merge_key 只做小写与去标点，不认识 &amp;，
    漏掉这一步会让同一篇论文的官网记录与日后的 DBLP 记录匹配不上。
    """
    return _SPACE.sub(" ", unescape(_TAG.sub("", fragment))).strip()


def _strip_affiliations(text: str) -> str:
    """剥掉内联的单位，反复剥到没有括号为止。

    _PAREN_GROUP 只匹配最内层（模式里排除了括号本身），所以嵌套的单位
    需要多轮才能剥净——实测 SOSP 2026 有
    "Ming-Chang Yang (The Chinese University of Hong Kong (CUHK))" 和
    "Ke Zhou (Wuhan National Laboratory for Optoelectronics (WNLO) of
    Huazhong University of Science and Technology (HUST))"。只跑一遍会留下
    "(The Chinese University of Hong Kong ," 这样的残片，再按逗号一切
    就变成了假作者名。
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
    """解析 USENIX technical-sessions 页面。

    keynote 与 speaker 块混在同样的 <article> 结构里，靠 /presentation/<slug>
    的 slug 区分：真论文的 slug 是作者名，keynote 的就叫 keynote。
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
            # 单位包在 <em> 里，整块删掉后剩下的就是纯人名序列。
            authors = _split_names(_text_of(_EM_BLOCK.sub(",", match.group(1))))

        papers.append(
            _make_paper(title, authors, venue, year, url=urljoin(_USENIX_BASE, href))
        )

    return papers


def parse_sigops_accepted(html: str, venue: str, year: int) -> List[Paper]:
    """解析 SIGOPS accepted-papers 页面（<ul class="paperlist"> 下的 <li>）。"""
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
            # 单位内联在括号里且自身含逗号（"(University of California,
            # Los Angeles)"），必须先剥括号再按逗号切，否则会切出假作者。
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
