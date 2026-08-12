from pathlib import Path

from csconf.dblp import parse_toc
from csconf.rounds import filter_by_rounds

FIXTURES = Path(__file__).parent / "fixtures"

# SIGMOD 2026's four rounds, from the official site: one edition spans vol 3 and vol 4
SIGMOD_2026_ROUNDS = [[3, 4], [3, 6], [4, 1], [4, 3]]


def _pacmmod_vol3():
    return parse_toc(
        (FIXTURES / "dblp-journals-pacmmod-pacmmod3-trimmed.xml").read_text(encoding="utf-8"),
        venue="SIGMOD",
        year=2026,
    )


def test_keeps_only_issues_listed_in_rounds():
    kept = filter_by_rounds(_pacmmod_vol3(), SIGMOD_2026_ROUNDS)

    assert {p.issue for p in kept} == {"4", "6"}
    assert kept, "vol 3 N4/N6 should keep papers"


def test_excludes_pods_issues_without_track_logic():
    """PODS issues (vol 3 N2 and N5) are not in SIGMOD's round list, so they
    fall out on their own and no track-filtering logic is needed."""
    kept = filter_by_rounds(_pacmmod_vol3(), SIGMOD_2026_ROUNDS)

    assert "2" not in {p.issue for p in kept}
    assert "5" not in {p.issue for p in kept}


def test_issue_number_alone_does_not_match_across_volumes():
    """Given only volume 4's issues, no volume 3 paper may survive.

    An earlier version compared issue numbers only and took the volume from
    the caller, so volume 3's N1/N3 were collected as volume 4's N1/N3 — one
    SIGMOD edition contaminated with another's papers.
    """
    kept = filter_by_rounds(_pacmmod_vol3(), [[4, 1], [4, 3]])

    assert kept == []


def test_matches_across_multiple_volumes_in_one_call():
    """Matching on (volume, issue) pairs, so papers from several volumes can
    be passed in at once."""
    papers = _pacmmod_vol3()
    kept = filter_by_rounds(papers, SIGMOD_2026_ROUNDS)

    assert all(p.volume == "3" for p in kept)
    assert {(p.volume, p.issue) for p in kept} == {("3", "4"), ("3", "6")}


def test_empty_rounds_keeps_nothing():
    assert filter_by_rounds(_pacmmod_vol3(), []) == []
