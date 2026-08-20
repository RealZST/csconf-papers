"""The published listing of data files.

raw.githubusercontent.com serves a file by path and cannot be asked what a
directory holds, so a consumer has no way to discover a venue that was added
after it last looked. data/index.json is that listing. Everything a consumer is
promised about it is asserted here rather than described in prose, because a
promise in a README cannot fail a build.
"""
import hashlib
import json

from csconf.models import Paper
from csconf.store import (
    INDEX_SCHEMA,
    rewrite_papers,
    scan_data_files,
    write_index,
    write_link_cache,
    write_venue_year,
)


def _paper(title, venue="SOSP", year=2025):
    return Paper(title=title, authors=[], venue=venue, year=year)


def _write(root, venue, year, titles, updated="2026-08-12"):
    return write_venue_year(
        root=root,
        venue=venue,
        year=year,
        papers=[_paper(t, venue, year) for t in titles],
        source_keys=["conf/x/x{}".format(year)],
        note=None,
        updated=updated,
    )


def _index(root):
    return json.loads((root / "data" / "index.json").read_text(encoding="utf-8"))


def test_lists_every_stored_venue_year(tmp_path):
    _write(tmp_path, "SOSP", 2025, ["A", "B"])
    _write(tmp_path, "EuroSys", 2026, ["C"])

    write_index(tmp_path, "2026-08-20")
    payload = _index(tmp_path)

    assert payload["schema"] == INDEX_SCHEMA
    assert payload["generated"] == "2026-08-20"
    assert {entry["path"] for entry in payload["files"]} == {
        "data/2025/SOSP.json",
        "data/2026/EuroSys.json",
    }


def test_every_listed_path_exists(tmp_path):
    """A consumer fetches these paths one by one. One that is not there turns a
    listing into a broken import."""
    _write(tmp_path, "SOSP", 2025, ["A"])
    _write(tmp_path, "VLDB", 2026, ["B", "C"])

    write_index(tmp_path, "2026-08-20")

    for entry in _index(tmp_path)["files"]:
        assert (tmp_path / entry["path"]).exists()


def test_venue_is_the_filename_spelling_and_the_meta_spelling(tmp_path):
    """One string, never transformed: venues.yaml's key becomes the filename in
    _path_for and meta.venue in write_venue_year. A consumer needs no mapping,
    and MobiCom must not arrive as MOBICOM."""
    _write(tmp_path, "MobiCom", 2026, ["A"])
    _write(tmp_path, "MLSys", 2025, ["B"])
    _write(tmp_path, "EuroSys", 2026, ["C"])

    write_index(tmp_path, "2026-08-20")

    for entry in _index(tmp_path)["files"]:
        stem = entry["path"].rsplit("/", 1)[-1][: -len(".json")]
        stored = json.loads((tmp_path / entry["path"]).read_text(encoding="utf-8"))
        assert entry["venue"] == stem
        assert entry["venue"] == stored["meta"]["venue"]

    assert {e["venue"] for e in _index(tmp_path)["files"]} == {
        "MobiCom", "MLSys", "EuroSys",
    }


def test_year_is_the_directory_and_the_meta_year(tmp_path):
    _write(tmp_path, "SOSP", 2025, ["A"])
    _write(tmp_path, "SOSP", 2026, ["B"])

    write_index(tmp_path, "2026-08-20")

    for entry in _index(tmp_path)["files"]:
        assert entry["path"] == "data/{}/SOSP.json".format(entry["year"])
        stored = json.loads((tmp_path / entry["path"]).read_text(encoding="utf-8"))
        assert entry["year"] == stored["meta"]["year"]


def test_paper_count_matches_the_papers_actually_in_the_file(tmp_path):
    """The consumer's tripwire. It compares what it parsed against this number,
    so it has to describe the file rather than what a run intended to write."""
    _write(tmp_path, "SOSP", 2025, ["A", "B", "C"])
    _write(tmp_path, "OSDI", 2026, ["D"])

    write_index(tmp_path, "2026-08-20")
    payload = _index(tmp_path)

    for entry in payload["files"]:
        stored = json.loads((tmp_path / entry["path"]).read_text(encoding="utf-8"))
        assert entry["paper_count"] == len(stored["papers"])
        assert entry["paper_count"] == stored["meta"]["paper_count"]

    assert payload["paper_count"] == 4


def test_sha256_is_over_the_bytes_that_are_served(tmp_path):
    path = _write(tmp_path, "SOSP", 2025, ["A", "B"])

    write_index(tmp_path, "2026-08-20")
    entry = _index(tmp_path)["files"][0]

    assert entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_cache_files_are_never_listed(tmp_path):
    """link-cache.json and its siblings sit at the root of data/ and are not
    paper files. The glob needs a year directory in between, so they are
    excluded by the shape of the scan rather than by a filter."""
    _write(tmp_path, "SOSP", 2025, ["A"])
    write_link_cache(tmp_path, {"some paper": {"url": "https://arxiv.org/abs/1"}})

    write_index(tmp_path, "2026-08-20")

    assert [e["path"] for e in _index(tmp_path)["files"]] == ["data/2025/SOSP.json"]


def test_the_index_does_not_list_itself(tmp_path):
    """It lives in data/ too. Twice, to prove a second run does not pick up the
    file the first one wrote."""
    _write(tmp_path, "SOSP", 2025, ["A"])

    write_index(tmp_path, "2026-08-20")
    write_index(tmp_path, "2026-08-21")

    assert [e["path"] for e in _index(tmp_path)["files"]] == ["data/2025/SOSP.json"]


def test_enrichment_changes_the_checksum_but_not_the_count(tmp_path):
    """meta.updated deliberately survives rewrite_papers, so it cannot tell a
    consumer that the bytes moved. sha256 is what makes filling in a link
    visible; a consumer caching on the date would pin the unenriched file."""
    _write(tmp_path, "SOSP", 2026, ["A"], updated="2026-08-12")
    write_index(tmp_path, "2026-08-20")
    before = _index(tmp_path)["files"][0]

    rewrite_papers(
        tmp_path, "SOSP", 2026,
        [Paper(title="A", authors=[], venue="SOSP", year=2026,
               url="https://arxiv.org/abs/1", url_source="semanticscholar")],
    )
    write_index(tmp_path, "2026-08-20")
    after = _index(tmp_path)["files"][0]

    assert after["updated"] == before["updated"] == "2026-08-12"
    assert after["paper_count"] == before["paper_count"] == 1
    assert after["sha256"] != before["sha256"]


def test_a_venue_that_failed_keeps_the_file_it_already_had(tmp_path):
    """A partial run must not produce an index that contradicts the repository.
    Nothing was written for OSDI, so nothing about OSDI appears; SOSP still
    describes the bytes on disk."""
    _write(tmp_path, "SOSP", 2025, ["A", "B"], updated="2026-07-01")

    write_index(tmp_path, "2026-08-20")
    payload = _index(tmp_path)

    assert [e["path"] for e in payload["files"]] == ["data/2025/SOSP.json"]
    assert payload["files"][0]["paper_count"] == 2
    assert payload["files"][0]["updated"] == "2026-07-01"


def test_entries_are_sorted_by_path(tmp_path):
    """So a monthly diff shows what changed instead of a reshuffle."""
    _write(tmp_path, "VLDB", 2026, ["A"])
    _write(tmp_path, "SOSP", 2025, ["B"])
    _write(tmp_path, "ASPLOS", 2025, ["C"])

    write_index(tmp_path, "2026-08-20")
    paths = [e["path"] for e in _index(tmp_path)["files"]]

    assert paths == sorted(paths)


def test_scan_reads_disk_not_a_run_result(tmp_path):
    """scan_data_files takes no papers argument by design: everything derived
    here is read back from the files, the same rule the README counts follow."""
    _write(tmp_path, "SOSP", 2025, ["A"])
    assert [e["paper_count"] for e in scan_data_files(tmp_path)] == [1]

    _write(tmp_path, "SOSP", 2025, ["A", "B"])
    assert [e["paper_count"] for e in scan_data_files(tmp_path)] == [2]
