from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from csconf import http, render, store, venues as venues_mod
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
        xml_text = fetcher.get(http.toc_url(fetch.toc_key))
        parsed = parse_toc(xml_text, venue=venue, year=year)

        if config["type"] == "journal_rounds":
            # 按 (卷, 期) 对匹配，卷号取自论文自身字段，不需要传 fetch.volume
            parsed = filter_by_rounds(parsed, rounds=config["rounds"][year])
        if config["type"] == "journal_volume":
            note = _note_for(config, year, fetch.volume)

        papers.extend(parsed)

    source_keys = [f.toc_key for f in fetches]
    status = venues_mod.status_of(venues, venue, year)

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
