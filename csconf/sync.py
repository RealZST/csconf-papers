from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from csconf import fallback, http, render, store, venues as venues_mod
from csconf.dblp import parse_toc
from csconf.models import Paper
from csconf.rounds import filter_by_rounds


class MappingDrift(Exception):
    """status 标为 indexed 的 venue-year 返回了 0 篇，多半是 DBLP 改了 key。"""


@dataclass
class SyncResult:
    venue: str
    year: int
    papers: List[Paper]
    note: Optional[str]
    source_keys: List[str]

    @property
    def paper_count(self) -> int:
        return len(self.papers)


def _note_for(config: Dict[str, Any], year: int, volume: Optional[int]) -> Optional[str]:
    template = config.get("note_template")
    if not template:
        return None
    return template.format(vol=volume, year=year)


def merge_sources(
    web_papers: List[Paper], dblp_papers: List[Paper]
) -> List[Paper]:
    """dblp 优先。同一篇论文的 web 记录被 dblp 记录替换而非叠加。"""
    merged = {p.merge_key(): p for p in web_papers}
    for paper in dblp_papers:
        merged[paper.merge_key()] = paper
    return list(merged.values())


def _fetch_fallback(
    config: Dict[str, Any], venue: str, year: int, fetcher
) -> List[Paper]:
    """DBLP 尚未编目时改抓官网。官网结构变了或页面不在，不该拖垮整届同步：
    这是补数据的兜底，失败就当没有，格子留破折号。"""
    url = config["fallback_url"].format(year=year, yy="{:02d}".format(year % 100))
    try:
        html = fetcher.get(url)
    except (http.HttpError, http.RateLimited) as exc:
        # 说出来。静默返回空列表时，日志里只剩 "0 papers"，分不清是
        # 「这届还没公布」还是「被站点拦了」——实测 USENIX 在反复请求后
        # 会开始拒绝，而这两种情况需要完全不同的处理。
        print("  fallback {} {} 失败: {}".format(venue, year, exc), file=sys.stderr)
        return []

    papers = fallback.parse_for(venue, html, year)
    if not papers:
        print(
            "  fallback {} {} 取到页面但解析出 0 篇，站点结构可能已变: {}".format(
                venue, year, url
            ),
            file=sys.stderr,
        )
    return papers


def sync_venue_year(
    root: Path,
    venues: Dict[str, Any],
    venue: str,
    year: int,
    fetcher,
    updated: str,
    allow_shrink: bool = False,
) -> SyncResult:
    config = venues[venue]

    def volume_lookup(index_key: str, lookup_year: int) -> List[int]:
        html = fetcher.get(http.index_url(index_key))
        slug = index_key.rsplit("/", 1)[-1]
        return venues_mod.discover_volumes(html, slug, lookup_year)

    fetches = venues_mod.expand(venues, venue, year, volume_lookup=volume_lookup)

    papers: List[Paper] = []
    note: Optional[str] = None
    for fetch in fetches:
        try:
            xml_text = fetcher.get(http.toc_url(fetch.toc_key))
        except http.NotFound:
            # TOC 尚不存在。对 pending 的会议这是正常状态（OSDI/ATC 2026 开完会
            # 但 DBLP 还没编目）；对 indexed 的会议则会在下面因零篇而触发
            # MappingDrift，正是想要的行为。
            continue
        parsed = parse_toc(xml_text, venue=venue, year=year)

        if config["type"] == "journal_rounds":
            # 按 (卷, 期) 对匹配，卷号取自论文自身字段，不需要传 fetch.volume
            parsed = filter_by_rounds(parsed, rounds=config["rounds"][year])
        if config["type"] == "journal_volume":
            note = _note_for(config, year, fetch.volume)

        papers.extend(parsed)

    source_keys = [f.toc_key for f in fetches]
    status = venues_mod.status_of(venues, venue, year)

    if not papers and status == "pending" and config.get("fallback_url"):
        # 会已经开完、官网早已挂出录用名单，DBLP 还没编目。先用官网顶上，
        # 等 DBLP 补上后再由 dblp 记录替换（merge_sources 里 dblp 优先）。
        papers = merge_sources(
            web_papers=_fetch_fallback(config, venue, year, fetcher),
            dblp_papers=papers,
        )

    if not papers:
        # indexed 却零篇 = DBLP 改了 TOC key，该届会安静消失，必须炸。
        if status == "indexed":
            raise MappingDrift(
                "{} {} 标为 indexed 却返回 0 篇，检查 venues.yaml 中的 TOC key".format(
                    venue, year
                )
            )
        # pending（尚未编目）与 partial（收录中但暂时还没有）在零篇时语义相同：
        # 数据还不存在。此时落文件会写出一个 0 篇的 JSON，README 随之显示
        # [0](papers/2026/OSDI.md)，把「还没有」渲染成「确实零篇」，正好毁掉
        # render_readme 里 — 与 0 的区分。什么都不写，格子留破折号。
        return SyncResult(
            venue=venue, year=year, papers=[], note=None, source_keys=source_keys
        )

    store.write_venue_year(
        root=root, venue=venue, year=year, papers=papers,
        source_keys=source_keys, note=note, updated=updated, allow_shrink=allow_shrink,
    )

    markdown = render.render_venue_year(venue, year, papers, note, updated)
    md_path = Path(root) / "papers" / str(year) / "{}.md".format(venue)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown, encoding="utf-8")

    return SyncResult(
        venue=venue, year=year, papers=papers, note=note, source_keys=source_keys
    )
