from csconf.models import Author, Paper
from csconf.render import render_readme, render_venue_year


def _paper(title, authors, doi=None):
    return Paper(
        title=title,
        authors=[Author(name=n) for n in authors],
        venue="SOSP",
        year=2025,
        doi=doi,
        url="https://doi.org/{}".format(doi) if doi else None,
    )


def test_venue_year_markdown_lists_papers_with_links():
    markdown = render_venue_year(
        venue="SOSP",
        year=2025,
        papers=[_paper("LithOS", ["Patrick H. Coppock", "Brian Zhang"], "10.1145/1")],
        note=None,
        updated="2026-08-12",
    )

    assert "# SOSP 2025" in markdown
    assert "1 papers" in markdown
    assert "[LithOS](https://doi.org/10.1145/1)" in markdown
    assert "Patrick H. Coppock, Brian Zhang" in markdown


def test_note_is_rendered_when_present():
    markdown = render_venue_year(
        venue="VLDB",
        year=2026,
        papers=[_paper("X", ["A"])],
        note="本文件为 PVLDB vol 19 全卷。",
        updated="2026-08-12",
    )

    assert "本文件为 PVLDB vol 19 全卷。" in markdown


def test_paper_without_doi_renders_as_plain_text():
    markdown = render_venue_year("SOSP", 2025, [_paper("NoDoi", ["A"])], None, "2026-08-12")

    assert "NoDoi" in markdown
    assert "[NoDoi](" not in markdown


def test_readme_matrix_has_year_rows_and_venue_columns():
    readme = render_readme(
        venues=["SOSP", "VLDB"],
        years=[2025, 2026],
        counts={("SOSP", 2025): 66, ("VLDB", 2026): 135},
        updated="2026-08-12",
    )

    rows = [line for line in readme.splitlines() if line.startswith("|")]

    assert rows[0] == "| Year | SOSP | VLDB |"
    # 整行比对：只断言子串的话，"| 2026 | — |" 会因为是下一行的前缀而巧合通过，
    # 并没有真验到空格子。
    assert rows[2] == "| 2025 | [66](papers/2025/SOSP.md) | — |"
    assert rows[3] == "| 2026 | — | [135](papers/2026/VLDB.md) |"


def test_readme_empty_cell_is_dash_not_zero():
    """没有数据的格子留破折号。写 0 会和「确实收录了零篇」混淆——
    OSDI/ATC 2026 正处在 DBLP 尚未编目的状态，两者含义完全不同。"""
    readme = render_readme(
        venues=["OSDI"], years=[2026], counts={}, updated="2026-08-12"
    )
    row = [line for line in readme.splitlines() if line.startswith("| 2026")][0]
    cells = [cell.strip() for cell in row.strip("|").split("|")]

    assert cells == ["2026", "—"]
