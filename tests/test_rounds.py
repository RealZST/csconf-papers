from pathlib import Path

from csconf.dblp import parse_toc
from csconf.rounds import filter_by_rounds

FIXTURES = Path(__file__).parent / "fixtures"

# SIGMOD 2026 的四轮，来自官方会议站点：一届横跨 vol 3 与 vol 4
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
    assert kept, "vol 3 的 N4/N6 应有论文留下"


def test_excludes_pods_issues_without_track_logic():
    """PODS 的期（vol 3 的 N2、N5）不在 SIGMOD 的 round 列表里，
    因此天然被排除，不需要任何 track 过滤逻辑。"""
    kept = filter_by_rounds(_pacmmod_vol3(), SIGMOD_2026_ROUNDS)

    assert "2" not in {p.issue for p in kept}
    assert "5" not in {p.issue for p in kept}


def test_issue_number_alone_does_not_match_across_volumes():
    """只给 vol 4 的期，vol 3 的论文一篇都不该留下。

    早期实现只比期号、卷号取自调用方传参，于是 vol 3 的 N1/N3 会被
    当成 vol 4 的 N1/N3 收进来——一届 SIGMOD 会混入另一届的论文。
    """
    kept = filter_by_rounds(_pacmmod_vol3(), [[4, 1], [4, 3]])

    assert kept == []


def test_matches_across_multiple_volumes_in_one_call():
    """按 (卷, 期) 对匹配，因此可以一次传入多卷的论文。"""
    papers = _pacmmod_vol3()
    kept = filter_by_rounds(papers, SIGMOD_2026_ROUNDS)

    assert all(p.volume == "3" for p in kept)
    assert {(p.volume, p.issue) for p in kept} == {("3", "4"), ("3", "6")}


def test_empty_rounds_keeps_nothing():
    assert filter_by_rounds(_pacmmod_vol3(), []) == []
