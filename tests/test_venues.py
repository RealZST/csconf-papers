from pathlib import Path

import pytest

from csconf.venues import Fetch, load_venues, expand

REPO_ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def venues():
    """Resolved from the repo root so the tests do not depend on pytest's cwd."""
    return load_venues(str(REPO_ROOT / "venues.yaml"))


def test_conference_expands_to_single_toc_key(venues):
    fetches = expand(venues, "SOSP", 2025, volume_lookup=None)

    assert fetches == [Fetch(toc_key="conf/sosp/sosp2025", volume=None)]


def test_atc_uses_usenix_key_not_atc(venues):
    """ATC's DBLP key is usenix{year}; writing atc{year} returns nothing at all."""
    fetches = expand(venues, "ATC", 2025, volume_lookup=None)

    assert fetches == [Fetch(toc_key="conf/usenix/usenix2025", volume=None)]


def test_journal_volume_maps_year_to_volume(venues):
    fetches = expand(venues, "VLDB", 2026, volume_lookup=None)

    assert fetches == [Fetch(toc_key="journals/pvldb/pvldb19", volume=19)]


def test_journal_rounds_expands_to_distinct_volumes(venues):
    """SIGMOD 2026's four rounds fall in volumes 3 and 4, so only two are fetched."""
    fetches = expand(venues, "SIGMOD", 2026, volume_lookup=None)

    assert fetches == [
        Fetch(toc_key="journals/pacmmod/pacmmod3", volume=3),
        Fetch(toc_key="journals/pacmmod/pacmmod4", volume=4),
    ]


def test_unknown_year_raises(venues):
    with pytest.raises(KeyError):
        expand(venues, "VLDB", 2030, volume_lookup=None)


def test_status_lookup(venues):
    from csconf.venues import status_of

    assert status_of(venues, "SOSP", 2025) == "indexed"
    assert status_of(venues, "SOSP", 2026) == "pending"
    assert status_of(venues, "NSDI", 2026) == "indexed"


def test_discover_volumes_from_index_html():
    from csconf.venues import discover_volumes

    html = (FIXTURES / "dblp-conf-asplos-index-trimmed.html").read_text(encoding="utf-8")

    assert discover_volumes(html, "asplos", 2025) == [1, 2, 3]
    assert discover_volumes(html, "asplos", 2024) == [1, 2, 3, 4]
    assert discover_volumes(html, "asplos", 2026) == [1, 2]
    assert discover_volumes(html, "asplos", 2030) == []


def test_asplos_expands_using_discovered_volumes(venues):
    html = (FIXTURES / "dblp-conf-asplos-index-trimmed.html").read_text(encoding="utf-8")
    from csconf.venues import discover_volumes

    def lookup(index_key, year):
        assert index_key == "conf/asplos"
        return discover_volumes(html, "asplos", year)

    fetches = expand(venues, "ASPLOS", 2025, volume_lookup=lookup)

    assert [f.toc_key for f in fetches] == [
        "conf/asplos/asplos2025-1",
        "conf/asplos/asplos2025-2",
        "conf/asplos/asplos2025-3",
    ]
