from pathlib import Path

import pytest

from csconf.sync import MappingDrift, sync_venue_year

FIXTURES = Path(__file__).parent / "fixtures"


class StubFetcher:
    """按 URL 返回预置内容，记录调用顺序。"""

    def __init__(self, mapping):
        self.mapping = mapping
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return self.mapping[url]


def test_sync_conference_writes_expected_count(tmp_path):
    venues = {
        "SOSP": {
            "type": "conf",
            "key": "conf/sosp/sosp{year}",
            "status": {2025: "indexed"},
        }
    }
    fetcher = StubFetcher(
        {
            "https://dblp.org/db/conf/sosp/sosp2025.xml": (
                FIXTURES / "dblp-conf-sosp-sosp2025.xml"
            ).read_text(encoding="utf-8")
        }
    )

    result = sync_venue_year(
        root=tmp_path, venues=venues, venue="SOSP", year=2025,
        fetcher=fetcher, updated="2026-08-12",
    )

    assert result.paper_count == 66
    assert (tmp_path / "data" / "2025" / "SOSP.json").exists()
    assert (tmp_path / "papers" / "2025" / "SOSP.md").exists()


def test_sync_sigmod_filters_to_rounds(tmp_path):
    venues = {
        "SIGMOD": {
            "type": "journal_rounds",
            "key": "journals/pacmmod/pacmmod{vol}",
            "rounds": {2026: [[3, 4], [3, 6]]},
            "status": {2026: "partial"},
        }
    }
    fetcher = StubFetcher(
        {
            "https://dblp.org/db/journals/pacmmod/pacmmod3.xml": (
                FIXTURES / "dblp-journals-pacmmod-pacmmod3-trimmed.xml"
            ).read_text(encoding="utf-8")
        }
    )

    result = sync_venue_year(
        root=tmp_path, venues=venues, venue="SIGMOD", year=2026,
        fetcher=fetcher, updated="2026-08-12",
    )

    assert {p.issue for p in result.papers} == {"4", "6"}


def test_sync_vldb_fills_note_from_template(tmp_path):
    venues = {
        "VLDB": {
            "type": "journal_volume",
            "key": "journals/pvldb/pvldb{vol}",
            "vol_for_year": {2026: 19},
            "note_template": "本文件为 PVLDB vol {vol} 全卷（VLDB {year}）。",
            "status": {2026: "partial"},
        }
    }
    fetcher = StubFetcher(
        {
            "https://dblp.org/db/journals/pvldb/pvldb19.xml": (
                FIXTURES / "dblp-journals-pvldb-pvldb19.xml"
            ).read_text(encoding="utf-8")
        }
    )

    result = sync_venue_year(
        root=tmp_path, venues=venues, venue="VLDB", year=2026,
        fetcher=fetcher, updated="2026-08-12",
    )

    assert result.paper_count == 135
    assert result.note == "本文件为 PVLDB vol 19 全卷（VLDB 2026）。"


def test_indexed_venue_with_zero_papers_raises(tmp_path):
    """status: indexed 却拿到 0 篇，说明 DBLP 改了 key，必须炸。"""
    venues = {
        "NSDI": {"type": "conf", "key": "conf/nsdi/nsdi{year}", "status": {2025: "indexed"}}
    }
    fetcher = StubFetcher({"https://dblp.org/db/conf/nsdi/nsdi2025.xml": "<bht></bht>"})

    with pytest.raises(MappingDrift):
        sync_venue_year(
            root=tmp_path, venues=venues, venue="NSDI", year=2025,
            fetcher=fetcher, updated="2026-08-12",
        )


def test_pending_venue_with_zero_papers_writes_nothing(tmp_path):
    """尚未编目的会议不能落 0 篇文件，否则 README 会把「未编目」显示成「零篇」。"""
    venues = {
        "OSDI": {"type": "conf", "key": "conf/osdi/osdi{year}", "status": {2026: "pending"}}
    }
    fetcher = StubFetcher({"https://dblp.org/db/conf/osdi/osdi2026.xml": "<bht></bht>"})

    result = sync_venue_year(
        root=tmp_path, venues=venues, venue="OSDI", year=2026,
        fetcher=fetcher, updated="2026-08-12",
    )

    assert result.paper_count == 0
    assert not (tmp_path / "data" / "2026" / "OSDI.json").exists()
    assert not (tmp_path / "papers" / "2026" / "OSDI.md").exists()


def test_asplos_fetches_index_then_each_volume(tmp_path):
    """多卷会议：先抓索引页发现卷号，再逐卷抓 TOC。"""
    venues = {
        "ASPLOS": {
            "type": "conf",
            "key": "conf/asplos/asplos{year}-{vol}",
            "volumes": "auto",
            "index": "conf/asplos",
            "status": {2025: "indexed"},
        }
    }
    index_html = (FIXTURES / "dblp-conf-asplos-index-trimmed.html").read_text(encoding="utf-8")
    sosp = (FIXTURES / "dblp-conf-sosp-sosp2025.xml").read_text(encoding="utf-8")
    fetcher = StubFetcher(
        {
            "https://dblp.org/db/conf/asplos/index.html": index_html,
            "https://dblp.org/db/conf/asplos/asplos2025-1.xml": sosp,
            "https://dblp.org/db/conf/asplos/asplos2025-2.xml": sosp,
            "https://dblp.org/db/conf/asplos/asplos2025-3.xml": sosp,
        }
    )

    result = sync_venue_year(
        root=tmp_path, venues=venues, venue="ASPLOS", year=2025,
        fetcher=fetcher, updated="2026-08-12",
    )

    assert fetcher.urls[0] == "https://dblp.org/db/conf/asplos/index.html"
    assert len(fetcher.urls) == 4
    assert result.source_keys == [
        "conf/asplos/asplos2025-1",
        "conf/asplos/asplos2025-2",
        "conf/asplos/asplos2025-3",
    ]


def test_partial_venue_with_zero_papers_also_writes_nothing(tmp_path):
    """partial（收录中但暂时还没有）与 pending 在零篇时语义相同：数据还不存在。

    早期实现只对 pending 提前返回，于是 partial 零篇会落一个 0 篇的 JSON，
    而 update.py 又因 paper_count 为假不给它 README 格子——文件存在、矩阵却
    显示破折号，两边不一致。
    """
    venues = {
        "SIGMOD": {
            "type": "journal_rounds",
            "key": "journals/pacmmod/pacmmod{vol}",
            "rounds": {2026: [[3, 4]]},
            "status": {2026: "partial"},
        }
    }
    # 返回一份没有任何 N4 论文的卷，过滤后必然为空
    fetcher = StubFetcher(
        {"https://dblp.org/db/journals/pacmmod/pacmmod3.xml": "<bht></bht>"}
    )

    result = sync_venue_year(
        root=tmp_path, venues=venues, venue="SIGMOD", year=2026,
        fetcher=fetcher, updated="2026-08-12",
    )

    assert result.paper_count == 0
    assert not (tmp_path / "data" / "2026" / "SIGMOD.json").exists()
    assert not (tmp_path / "papers" / "2026" / "SIGMOD.md").exists()
