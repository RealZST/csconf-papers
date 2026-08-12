import json

import pytest

from csconf.models import Paper
from csconf.store import ShrinkRejected, load_papers, write_venue_year


def _paper(title, venue="SOSP", year=2025):
    return Paper(title=title, authors=[], venue=venue, year=year)


def test_writes_meta_and_papers(tmp_path):
    path = write_venue_year(
        root=tmp_path,
        venue="VLDB",
        year=2026,
        papers=[_paper("A", "VLDB", 2026), _paper("B", "VLDB", 2026)],
        source_keys=["journals/pvldb/pvldb19"],
        note="本文件为 PVLDB vol 19 全卷。",
        updated="2026-08-12",
    )

    assert path == tmp_path / "data" / "2026" / "VLDB.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["meta"]["venue"] == "VLDB"
    assert payload["meta"]["paper_count"] == 2
    assert payload["meta"]["source_keys"] == ["journals/pvldb/pvldb19"]
    assert payload["meta"]["note"].startswith("本文件为 PVLDB vol 19")
    assert [p["title"] for p in payload["papers"]] == ["A", "B"]


def test_growth_is_allowed(tmp_path):
    write_venue_year(tmp_path, "SOSP", 2025, [_paper("A")], [], None, "2026-08-12")
    write_venue_year(
        tmp_path, "SOSP", 2025, [_paper("A"), _paper("B")], [], None, "2026-08-12"
    )

    assert len(load_papers(tmp_path, "SOSP", 2025)) == 2


def test_shrink_is_rejected_by_default(tmp_path):
    write_venue_year(tmp_path, "SOSP", 2025, [_paper("A"), _paper("B")], [], None, "2026-08-12")

    with pytest.raises(ShrinkRejected):
        write_venue_year(tmp_path, "SOSP", 2025, [_paper("A")], [], None, "2026-08-12")

    # 旧数据必须原样保留
    assert len(load_papers(tmp_path, "SOSP", 2025)) == 2


def test_shrink_allowed_with_flag(tmp_path):
    write_venue_year(tmp_path, "SOSP", 2025, [_paper("A"), _paper("B")], [], None, "2026-08-12")

    write_venue_year(
        tmp_path, "SOSP", 2025, [_paper("A")], [], None, "2026-08-12", allow_shrink=True
    )

    assert len(load_papers(tmp_path, "SOSP", 2025)) == 1
