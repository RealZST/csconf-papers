#!/usr/bin/env python3
"""csconf-papers: 从 DBLP 同步顶会录用论文列表。"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import requests

from csconf import http, render, store, venues as venues_mod
from csconf.sync import MappingDrift, sync_venue_year

ROOT = Path(__file__).parent
YEARS = [2025, 2026]


def cmd_sync(args: argparse.Namespace) -> int:
    venues = venues_mod.load_venues(str(ROOT / "venues.yaml"))
    fetcher = http.Fetcher(session=requests.Session())
    updated = args.today or dt.date.today().isoformat()

    counts = {}
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
                if result.paper_count:
                    counts[(venue, year)] = result.paper_count
                print("{} {}: {} papers".format(venue, year, result.paper_count))
            except (MappingDrift, store.ShrinkRejected, http.RateLimited, http.HttpError) as exc:
                failures.append("{} {}: {}".format(venue, year, exc))
                print("FAIL {} {}: {}".format(venue, year, exc), file=sys.stderr)

    readme = render.render_readme(list(venues), YEARS, counts, updated)
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

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
