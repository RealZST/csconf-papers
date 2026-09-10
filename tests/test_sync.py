from pathlib import Path

import pytest

from csconf import dblp
from csconf.sync import MappingDrift, sync_venue_year

FIXTURES = Path(__file__).parent / "fixtures"

EMPTY_RESULT = '{"head": {"vars": []}, "results": {"bindings": []}}'


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
            dblp.toc_query_url("conf/sosp/sosp2025"): (
                FIXTURES / "sparql-conf-sosp-sosp2025.json"
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
            dblp.toc_query_url("journals/pacmmod/pacmmod3"): (
                FIXTURES / "sparql-journals-pacmmod-pacmmod3-trimmed.json"
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
            dblp.toc_query_url("journals/pvldb/pvldb19"): (
                FIXTURES / "sparql-journals-pvldb-pvldb19-trimmed.json"
            ).read_text(encoding="utf-8")
        }
    )

    result = sync_venue_year(
        root=tmp_path, venues=venues, venue="VLDB", year=2026,
        fetcher=fetcher, updated="2026-08-12",
    )

    assert result.paper_count == 30
    assert result.note == "All of PVLDB vol 19 (VLDB 2026)."


def test_indexed_venue_with_zero_papers_raises(tmp_path):
    """Indexed but zero papers means the DBLP key changed, and that must be loud."""
    venues = {
        "NSDI": {"type": "conf", "key": "conf/nsdi/nsdi{year}", "status": {2025: "indexed"}}
    }
    fetcher = StubFetcher({dblp.toc_query_url("conf/nsdi/nsdi2025"): EMPTY_RESULT})

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
    fetcher = StubFetcher({dblp.toc_query_url("conf/osdi/osdi2026"): EMPTY_RESULT})

    result = sync_venue_year(
        root=tmp_path, venues=venues, venue="OSDI", year=2026,
        fetcher=fetcher, updated="2026-08-12",
    )

    assert result.paper_count == 0
    assert not (tmp_path / "data" / "2026" / "OSDI.json").exists()
    assert not (tmp_path / "papers" / "2026" / "OSDI.md").exists()


def test_asplos_fetches_stream_tocs_then_each_volume(tmp_path):
    """Multi-volume venue: query the stream's TOC pages to discover volumes,
    then each volume's TOC."""
    venues = {
        "ASPLOS": {
            "type": "conf",
            "key": "conf/asplos/asplos{year}-{vol}",
            "volumes": "auto",
            "index": "conf/asplos",
            "status": {2025: "indexed"},
        }
    }
    tocs = (FIXTURES / "sparql-conf-asplos-tocs-trimmed.json").read_text(encoding="utf-8")
    sosp = (FIXTURES / "sparql-conf-sosp-sosp2025.json").read_text(encoding="utf-8")
    fetcher = StubFetcher(
        {
            dblp.stream_tocs_query_url("conf/asplos"): tocs,
            dblp.toc_query_url("conf/asplos/asplos2025-1"): sosp,
            dblp.toc_query_url("conf/asplos/asplos2025-2"): sosp,
            dblp.toc_query_url("conf/asplos/asplos2025-3"): sosp,
        }
    )

    result = sync_venue_year(
        root=tmp_path, venues=venues, venue="ASPLOS", year=2025,
        fetcher=fetcher, updated="2026-08-12",
    )

    assert fetcher.urls[0] == dblp.stream_tocs_query_url("conf/asplos")
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
        {dblp.toc_query_url("journals/pacmmod/pacmmod3"): EMPTY_RESULT}
    )

    result = sync_venue_year(
        root=tmp_path, venues=venues, venue="SIGMOD", year=2026,
        fetcher=fetcher, updated="2026-08-12",
    )

    assert result.paper_count == 0
    assert not (tmp_path / "data" / "2026" / "SIGMOD.json").exists()
    assert not (tmp_path / "papers" / "2026" / "SIGMOD.md").exists()


def test_missing_toc_is_treated_as_no_data_for_pending_venue(tmp_path):
    """A pending venue whose fetch 404s writes nothing, exactly like an empty
    result. The SPARQL endpoint answers an unknown TOC with zero rows rather
    than a 404, but the transport can still produce one."""
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
            dblp.toc_query_url("conf/osdi/osdi2026"): EMPTY_RESULT,
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


def test_dblp_failure_still_reaches_the_fallback_for_pending_venue(tmp_path):
    """A DBLP-side failure must not take the conference-site fallback down with
    it. When Anubis went up in front of dblp.org in September 2026, SOSP 2026
    failed on the DBLP fetch and never reached the SIGOPS page that had its 62
    papers all along."""
    challenge = "<!doctype html><html><head><title>Making sure you're not a bot!</title></head></html>"
    venues = {
        "SOSP": {
            "type": "conf",
            "key": "conf/sosp/sosp{year}",
            "fallback_url": "https://www.sigops.org/s/conferences/sosp/{year}/accepted.html",
            "status": {2026: "pending"},
        }
    }
    fetcher = StubFetcher(
        {
            dblp.toc_query_url("conf/sosp/sosp2026"): challenge,
            "https://www.sigops.org/s/conferences/sosp/2026/accepted.html": (
                FIXTURES / "sigops-sosp-2026-accepted.html"
            ).read_text(encoding="utf-8"),
        }
    )

    result = sync_venue_year(
        root=tmp_path, venues=venues, venue="SOSP", year=2026,
        fetcher=fetcher, updated="2026-08-12",
    )

    assert result.paper_count > 0
    assert {p.source for p in result.papers} == {"sosp-web"}
    assert (tmp_path / "data" / "2026" / "SOSP.json").exists()


def test_dblp_failure_on_indexed_venue_stays_loud(tmp_path):
    """An indexed venue has no site fallback to hide behind: DBLP's data IS the
    data, and a broken fetch has to fail the venue rather than quietly keep
    yesterday's file without saying why."""
    challenge = "<!doctype html><html><head><title>Making sure you're not a bot!</title></head></html>"
    venues = {
        "NSDI": {"type": "conf", "key": "conf/nsdi/nsdi{year}", "status": {2025: "indexed"}}
    }
    fetcher = StubFetcher({dblp.toc_query_url("conf/nsdi/nsdi2025"): challenge})

    with pytest.raises(dblp.BadResponse):
        sync_venue_year(
            root=tmp_path, venues=venues, venue="NSDI", year=2025,
            fetcher=fetcher, updated="2026-08-12",
        )


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
            if url.startswith(dblp.SPARQL_ENDPOINT):
                return EMPTY_RESULT
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
    dblp_papers = [Paper(title="LithOS: An OS for ML on GPUs.", authors=[], venue="OSDI",
                         year=2026, source="dblp")]

    merged = merge_sources(web_papers=web, dblp_papers=dblp_papers)

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
