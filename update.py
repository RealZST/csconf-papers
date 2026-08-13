#!/usr/bin/env python3
"""csconf-papers: sync accepted-paper lists for top venues from DBLP."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from csconf import enrich, http, pdf, preprint, render, store, venues as venues_mod
from csconf.models import Paper
from csconf.sync import MappingDrift, sync_venue_year

ROOT = Path(__file__).parent
YEARS = [2025, 2026]


def counts_on_disk() -> dict:
    """README counts always come from the JSON on disk, never from this run.

    Failed fetches are normal, especially for the conference-site fallback:
    USENIX starts blocking after repeated requests. If the counts came from the
    sync results, one failure would empty a README cell while the matching JSON
    still sat on disk intact — the file saying 136 papers and the matrix saying
    no data. Reading from disk makes that contradiction impossible; a failed
    fetch simply means no update this round.
    """
    counts = {}
    for path in sorted((ROOT / "data").glob("*/*.json")):
        meta = json.loads(path.read_text(encoding="utf-8"))["meta"]
        if meta["paper_count"]:
            counts[(meta["venue"], meta["year"])] = meta["paper_count"]
    return counts


def cmd_render(args: argparse.Namespace) -> int:
    """Regenerate the derived outputs from stored JSON, fully offline.

    That means the Markdown listings, the README, and the derived fields inside
    the JSON itself — display_name is computed on every write, so re-writing the
    files is how a change to that rule reaches data already on disk. The paper
    count cannot change here, and rewrite_papers refuses if it does.

    Changing any of this should not mean pulling two thousand papers from DBLP
    again: that takes well over ten minutes and loads a third-party service
    that already rate-limits us hard.
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

        store.rewrite_papers(ROOT, meta["venue"], meta["year"], papers)

        print("{} {}: {} papers".format(meta["venue"], meta["year"], len(papers)))

    updated = args.today or dt.date.today().isoformat()
    (ROOT / "README.md").write_text(
        render.render_readme(list(venues), YEARS, counts_on_disk(), updated),
        encoding="utf-8",
    )
    return 0


def cmd_enrich(args: argparse.Namespace) -> int:
    """Give every paper a link to read it by, and a PDF link where one exists.

    Editions DBLP has not indexed are scraped from the conference site, which
    carries titles and authors only — the SIGOPS SOSP accepted page has no
    links in it at all. Those titles are matched against Semantic Scholar,
    usually landing on the authors' own arXiv preprint. PDF URLs are then
    derived from whatever link each paper has.

    This always returns 0. Filling in links is a bonus, and finding none must
    not turn CI red, or the sync failures that do matter drown in the noise.
    """
    today = args.today or dt.date.today().isoformat()
    # Semantic Scholar's anonymous quota is shared by every caller on the
    # internet, so throttle harder here than for DBLP.
    matcher = http.Fetcher(session=enrich.build_session(), throttle_seconds=3.0)
    # HEAD checks go to the publishers themselves, which are far less touchy.
    checker = http.Fetcher(session=requests.Session(), throttle_seconds=1.0)

    link_cache = store.load_link_cache(ROOT)
    pdf_cache = store.load_pdf_cache(ROOT)
    arxiv_cache = store.load_arxiv_cache(ROOT)
    lookup_budget, verify_budget = args.budget, args.pdf_budget
    preprint_budget = args.preprint_budget

    totals = {"found": 0, "queried": 0, "filled": 0, "checked": 0, "preprints": 0}
    for path in sorted((ROOT / "data").glob("*/*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        meta = payload["meta"]
        papers = [Paper.from_dict(item) for item in payload["papers"]]
        before = [(p.url, p.pdf_url, p.arxiv_id) for p in papers]

        papers, link_cache, link_stats = enrich.enrich_papers(
            papers, cache=link_cache, fetcher=matcher, today=today, budget=lookup_budget
        )
        lookup_budget -= link_stats["queried"]

        papers, pdf_cache, pdf_stats = pdf.fill_pdfs(
            papers, cache=pdf_cache, head=checker.head_is_pdf, budget=verify_budget
        )
        verify_budget -= pdf_stats["checked"]

        papers, arxiv_cache, pre_stats = preprint.fill_arxiv_ids(
            papers, cache=arxiv_cache, fetcher=matcher, today=today,
            budget=preprint_budget,
        )
        preprint_budget -= pre_stats["requests"]

        totals["found"] += link_stats["found"]
        totals["queried"] += link_stats["queried"]
        totals["filled"] += pdf_stats["filled"]
        totals["checked"] += pdf_stats["checked"]
        totals["preprints"] += pre_stats["found"] + pre_stats["cached"]

        if [(p.url, p.pdf_url, p.arxiv_id) for p in papers] != before:
            store.rewrite_papers(ROOT, meta["venue"], meta["year"], papers)
            markdown = render.render_venue_year(
                meta["venue"], meta["year"], papers, meta.get("note"), meta["updated"]
            )
            md_path = ROOT / "papers" / str(meta["year"]) / "{}.md".format(meta["venue"])
            md_path.write_text(markdown, encoding="utf-8")

        print(
            "{} {}: +{} links, +{} pdfs, +{} preprints".format(
                meta["venue"], meta["year"], link_stats["found"], pdf_stats["filled"],
                pre_stats["found"] + pre_stats["cached"],
            )
        )
        # Save after every venue: a run that dies halfway should not throw away
        # the lookups it already paid for.
        store.write_link_cache(ROOT, link_cache)
        store.write_pdf_cache(ROOT, pdf_cache)
        store.write_arxiv_cache(ROOT, arxiv_cache)

        if (
            link_stats["budget_exhausted"]
            or pdf_stats["budget_exhausted"]
            or pre_stats["budget_exhausted"]
        ):
            # Keep going rather than break. Spending the request budget must not
            # stop the derivations that need no request at all: the first real
            # run stopped here and left VLDB 2026's 135 papers without PDF
            # links, every one of which was free to derive.
            print(
                "  {} {}: request budget spent; later venues keep their free "
                "derivations and the rest waits for the next run".format(
                    meta["venue"], meta["year"]
                ),
                file=sys.stderr,
            )

    print(
        "total: +{} links ({} queries), +{} pdfs ({} checks), {} preprints".format(
            totals["found"], totals["queried"], totals["filled"], totals["checked"],
            totals["preprints"],
        )
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
        print("\n{} venue-years failed:".format(len(failures)), file=sys.stderr)
        for line in failures:
            print("  - " + line, file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="sync paper lists from DBLP")
    sync.add_argument(
        "--allow-shrink",
        action="store_true",
        help="allow the paper count to drop. Only for a legitimate shrink "
        "caused by a venues.yaml change; CI must never pass this.",
    )
    sync.add_argument("--today", help="override the updated date, for reproducible runs")
    sync.set_defaults(func=cmd_sync)

    render_parser = sub.add_parser(
        "render", help="regenerate Markdown and README from stored JSON, offline"
    )
    render_parser.add_argument("--today", help="override the updated date")
    render_parser.set_defaults(func=cmd_render)

    enrich_parser = sub.add_parser(
        "enrich", help="fill in missing source links and PDF links"
    )
    enrich_parser.add_argument(
        "--budget",
        type=int,
        default=enrich.DEFAULT_BUDGET,
        help="how many title lookups to make this run; the rest wait",
    )
    enrich_parser.add_argument(
        "--pdf-budget",
        type=int,
        default=pdf.DEFAULT_VERIFY_BUDGET,
        help="how many derived PDF URLs to verify this run; the rest wait",
    )
    enrich_parser.add_argument(
        "--preprint-budget",
        type=int,
        default=preprint.DEFAULT_BUDGET,
        help="how many DOI batch requests to make this run (500 DOIs each)",
    )
    enrich_parser.add_argument("--today", help="override the cache check date")
    enrich_parser.set_defaults(func=cmd_enrich)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
