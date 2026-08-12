#!/usr/bin/env python3
"""csconf-papers: 从 DBLP 同步顶会录用论文列表。"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from csconf import http, render, store, venues as venues_mod
from csconf.models import Paper
from csconf.sync import MappingDrift, sync_venue_year

ROOT = Path(__file__).parent
YEARS = [2025, 2026]


def counts_on_disk() -> dict:
    """README 的计数一律取自磁盘上的 JSON，而不是本次同步的返回值。

    抓取失败是常态——官网兜底尤其如此，USENIX 在反复请求后会开始拦截。
    若计数来自同步结果，一次失败就会让 README 少掉一格，而对应的 JSON
    还完好地躺在磁盘上：文件说 136 篇，矩阵说没有数据。以磁盘为准则
    两者不可能矛盾，抓取失败只是意味着这一轮没有更新。
    """
    counts = {}
    for path in sorted((ROOT / "data").glob("*/*.json")):
        meta = json.loads(path.read_text(encoding="utf-8"))["meta"]
        if meta["paper_count"]:
            counts[(meta["venue"], meta["year"])] = meta["paper_count"]
    return counts


def cmd_render(args: argparse.Namespace) -> int:
    """从已存 JSON 重新生成 Markdown 与 README，完全不联网。

    改渲染逻辑不该需要重新从 DBLP 拉两千篇论文——那要十几分钟，还平白
    给一个已经限流严重的第三方服务加压。
    """
    venues = venues_mod.load_venues(str(ROOT / "venues.yaml"))

    for path in sorted((ROOT / "data").glob("*/*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        meta = payload["meta"]
        papers = [Paper.from_dict(item) for item in payload["papers"]]
        updated = args.today or meta["updated"]

        markdown = render.render_venue_year(
            meta["venue"], meta["year"], papers, meta.get("note"), updated
        )
        md_path = ROOT / "papers" / str(meta["year"]) / "{}.md".format(meta["venue"])
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(markdown, encoding="utf-8")

        print("{} {}: {} papers".format(meta["venue"], meta["year"], len(papers)))

    updated = args.today or dt.date.today().isoformat()
    (ROOT / "README.md").write_text(
        render.render_readme(list(venues), YEARS, counts_on_disk(), updated),
        encoding="utf-8",
    )
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    venues = venues_mod.load_venues(str(ROOT / "venues.yaml"))
    fetcher = http.Fetcher(session=requests.Session())
    updated = args.today or dt.date.today().isoformat()

    failures = []
    for venue in venues:
        for year in YEARS:
            if venues_mod.status_of(venues, venue, year) is None:
                continue
            try:
                result = sync_venue_year(
                    root=ROOT, venues=venues, venue=venue, year=year,
                    fetcher=fetcher, updated=updated, allow_shrink=args.allow_shrink,
                )
                print("{} {}: {} papers".format(venue, year, result.paper_count))
            except (
                MappingDrift,
                store.ShrinkRejected,
                http.RateLimited,
                http.HttpError,
                ET.ParseError,
            ) as exc:
                failures.append("{} {}: {}".format(venue, year, exc))
                print("FAIL {} {}: {}".format(venue, year, exc), file=sys.stderr)

    readme = render.render_readme(list(venues), YEARS, counts_on_disk(), updated)
    (ROOT / "README.md").write_text(readme, encoding="utf-8")

    if failures:
        print("\n{} 个 venue-year 失败：".format(len(failures)), file=sys.stderr)
        for line in failures:
            print("  - " + line, file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="从 DBLP 同步论文列表")
    sync.add_argument(
        "--allow-shrink",
        action="store_true",
        help="放行条数下降。仅在 venues.yaml 配置变更导致的正当缩减时使用，CI 不得带此参数。",
    )
    sync.add_argument("--today", help="覆盖 updated 日期，便于可复现的测试运行")
    sync.set_defaults(func=cmd_sync)

    render_parser = sub.add_parser(
        "render", help="从已存 JSON 重新生成 Markdown 与 README，不联网"
    )
    render_parser.add_argument("--today", help="覆盖 updated 日期")
    render_parser.set_defaults(func=cmd_render)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
