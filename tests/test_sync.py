from pathlib import Path

import pytest

from csconf.sync import MappingDrift, sync_venue_year

FIXTURES = Path(__file__).parent / "fixtures"


class StubFetcher:
    """Returns canned content per URL and records the order of calls."""

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
            "note_template": "All of PVLDB vol {vol} (VLDB {year}).",
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
    assert result.note == "All of PVLDB vol 19 (VLDB 2026)."


def test_indexed_venue_with_zero_papers_raises(tmp_path):
    """Indexed but zero papers means the DBLP key changed, and that must be loud."""
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
    """An unindexed edition must not write a 0-paper file, or the README renders
    "not indexed yet" as "genuinely zero papers"."""
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
    """Multi-volume venue: fetch the index to discover volumes, then each TOC."""
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
    """At zero papers, partial (indexed but nothing yet) means the same as
    pending: the data does not exist.

    An earlier version returned early for pending only, so a partial with zero
    papers wrote a 0-paper JSON while update.py, seeing a falsy paper_count,
    left its README cell empty — the file existing and the matrix showing an em
    dash, disagreeing with each other.
    """
    venues = {
        "SIGMOD": {
            "type": "journal_rounds",
            "key": "journals/pacmmod/pacmmod{vol}",
            "rounds": {2026: [[3, 4]]},
            "status": {2026: "partial"},
        }
    }
    # A volume with no N4 papers at all, so filtering necessarily empties it
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


def test_missing_toc_is_treated_as_no_data_for_pending_venue(tmp_path):
    """OSDI/ATC 2026 happened but DBLP has not indexed them, so their TOCs 404.
    For a pending venue that is the normal state and not a failure."""
    from csconf.http import NotFound

    class NotFoundFetcher:
        def get(self, url):
            raise NotFound("{} does not exist".format(url), 404)

    venues = {
        "OSDI": {"type": "conf", "key": "conf/osdi/osdi{year}", "status": {2026: "pending"}}
    }

    result = sync_venue_year(
        root=tmp_path, venues=venues, venue="OSDI", year=2026,
        fetcher=NotFoundFetcher(), updated="2026-08-12",
    )

    assert result.paper_count == 0
    assert not (tmp_path / "data" / "2026" / "OSDI.json").exists()


def test_pending_venue_falls_back_to_official_site(tmp_path):
    """When DBLP has not indexed but the site has published, fill from the site so
    the README cell is not an em dash."""
    venues = {
        "OSDI": {
            "type": "conf",
            "key": "conf/osdi/osdi{year}",
            "fallback_url": "https://www.usenix.org/conference/osdi{yy}/technical-sessions",
            "status": {2026: "pending"},
        }
    }
    fetcher = StubFetcher(
        {
            "https://dblp.org/db/conf/osdi/osdi2026.xml": "<bht></bht>",
            "https://www.usenix.org/conference/osdi26/technical-sessions": (
                FIXTURES / "usenix-osdi-2026-accepted.html"
            ).read_text(encoding="utf-8"),
        }
    )

    result = sync_venue_year(
        root=tmp_path, venues=venues, venue="OSDI", year=2026,
        fetcher=fetcher, updated="2026-08-12",
    )

    assert result.paper_count == 5
    assert {p.source for p in result.papers} == {"osdi-web"}
    assert (tmp_path / "data" / "2026" / "OSDI.json").exists()
    assert (tmp_path / "papers" / "2026" / "OSDI.md").exists()


def test_fallback_failure_leaves_venue_empty_instead_of_aborting(tmp_path):
    """When the site cannot be reached either, stay quiet: a failed fallback must
    not mark the edition as failed."""
    from csconf.http import NotFound

    venues = {
        "OSDI": {
            "type": "conf",
            "key": "conf/osdi/osdi{year}",
            "fallback_url": "https://www.usenix.org/conference/osdi{yy}/technical-sessions",
            "status": {2026: "pending"},
        }
    }

    class FallbackNotFoundFetcher:
        def get(self, url):
            if url.startswith("https://dblp.org/"):
                return "<bht></bht>"
            raise NotFound("{} does not exist".format(url), 404)

    result = sync_venue_year(
        root=tmp_path, venues=venues, venue="OSDI", year=2026,
        fetcher=FallbackNotFoundFetcher(), updated="2026-08-12",
    )

    assert result.paper_count == 0
    assert not (tmp_path / "data" / "2026" / "OSDI.json").exists()


def test_dblp_records_replace_web_records_without_duplicates():
    """Once DBLP indexes an edition its records take over the site ones: matched
    on the normalised title and replaced, not appended. This outranks the
    grow-only rule."""
    from csconf.models import Paper
    from csconf.sync import merge_sources

    web = [Paper(title="LithOS: An OS for ML on GPUs", authors=[], venue="OSDI",
                 year=2026, source="osdi-web")]
    dblp = [Paper(title="LithOS: An OS for ML on GPUs.", authors=[], venue="OSDI",
                  year=2026, source="dblp")]

    merged = merge_sources(web_papers=web, dblp_papers=dblp)

    assert len(merged) == 1
    assert merged[0].source == "dblp"


def test_missing_toc_on_indexed_venue_still_raises_drift(tmp_path):
    """An indexed venue whose TOC 404s means the DBLP key changed; that has to be
    loud, not silently skipped."""
    from csconf.http import NotFound

    class NotFoundFetcher:
        def get(self, url):
            raise NotFound("{} does not exist".format(url), 404)

    venues = {
        "NSDI": {"type": "conf", "key": "conf/nsdi/nsdi{year}", "status": {2025: "indexed"}}
    }

    with pytest.raises(MappingDrift):
        sync_venue_year(
            root=tmp_path, venues=venues, venue="NSDI", year=2025,
            fetcher=NotFoundFetcher(), updated="2026-08-12",
        )
