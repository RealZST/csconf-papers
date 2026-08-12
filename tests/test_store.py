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
        note="All of PVLDB vol 19.",
        updated="2026-08-12",
    )

    assert path == tmp_path / "data" / "2026" / "VLDB.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["meta"]["venue"] == "VLDB"
    assert payload["meta"]["paper_count"] == 2
    assert payload["meta"]["source_keys"] == ["journals/pvldb/pvldb19"]
    assert payload["meta"]["note"].startswith("All of PVLDB vol 19")
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

    # The existing data has to survive untouched
    assert len(load_papers(tmp_path, "SOSP", 2025)) == 2


def test_shrink_allowed_with_flag(tmp_path):
    write_venue_year(tmp_path, "SOSP", 2025, [_paper("A"), _paper("B")], [], None, "2026-08-12")

    write_venue_year(
        tmp_path, "SOSP", 2025, [_paper("A")], [], None, "2026-08-12", allow_shrink=True
    )

    assert len(load_papers(tmp_path, "SOSP", 2025)) == 1


def test_rewrite_papers_keeps_meta(tmp_path):
    """Filling in links replaces papers only. meta.updated records when this
    list was collected, and filling in links refetched nothing, so changing it
    would be a false claim."""
    from csconf.store import rewrite_papers

    write_venue_year(
        tmp_path, "SOSP", 2026, [_paper("A", "SOSP", 2026)],
        ["conf/sosp/sosp2026"], "note", "2026-08-12",
    )
    linked = Paper(
        title="A", authors=[], venue="SOSP", year=2026,
        url="https://arxiv.org/abs/1", url_source="semanticscholar",
    )

    path = rewrite_papers(tmp_path, "SOSP", 2026, [linked])
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["meta"] == {
        "venue": "SOSP", "year": 2026, "source_keys": ["conf/sosp/sosp2026"],
        "paper_count": 1, "note": "note", "updated": "2026-08-12",
    }
    assert payload["papers"][0]["url"] == "https://arxiv.org/abs/1"
    assert payload["papers"][0]["url_source"] == "semanticscholar"


def test_rewrite_papers_refuses_to_change_the_paper_set(tmp_path):
    """This entry point exists to change fields. A changed count means the
    caller passed the wrong data, and writing it anyway would bypass the shrink
    guard in write_venue_year."""
    from csconf.store import rewrite_papers

    write_venue_year(tmp_path, "SOSP", 2026, [_paper("A", "SOSP", 2026)], [], None, "2026-08-12")

    with pytest.raises(ValueError):
        rewrite_papers(tmp_path, "SOSP", 2026, [])


def test_link_cache_roundtrip(tmp_path):
    from csconf.store import load_link_cache, write_link_cache

    assert load_link_cache(tmp_path) == {}

    write_link_cache(tmp_path, {"some paper": {"url": "https://arxiv.org/abs/1"}})

    assert load_link_cache(tmp_path)["some paper"]["url"] == "https://arxiv.org/abs/1"
