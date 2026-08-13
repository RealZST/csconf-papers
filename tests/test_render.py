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
        note="All of PVLDB vol 19.",
        updated="2026-08-12",
    )

    assert "All of PVLDB vol 19." in markdown


def test_paper_without_a_link_is_no_longer_left_as_plain_text():
    """The old behaviour was plain text. Falling back to a Scholar search URL
    saves the reader from copying a bare title into a search box for an address
    we can build ourselves."""
    markdown = render_venue_year("SOSP", 2025, [_paper("NoDoi", ["A"])], None, "2026-08-12")

    assert "[NoDoi](https://scholar.google.com/scholar?q=NoDoi)" in markdown


def test_readme_matrix_has_year_rows_and_venue_columns():
    readme = render_readme(
        venues=["SOSP", "VLDB"],
        years=[2025, 2026],
        counts={("SOSP", 2025): 66, ("VLDB", 2026): 135},
        updated="2026-08-12",
    )

    rows = [line for line in readme.splitlines() if line.startswith("|")]

    assert rows[0] == "| Year | SOSP | VLDB |"
    # Compare whole rows: as a substring, "| 2026 | — |" would pass by accident
    # because it prefixes the next row, testing nothing about the empty cell.
    assert rows[2] == "| 2025 | [66](papers/2025/SOSP.md) | — |"
    assert rows[3] == "| 2026 | — | [135](papers/2026/VLDB.md) |"


def test_readme_empty_cell_is_dash_not_zero():
    """A cell with no data gets an em dash. Writing 0 would be confused with
    "this edition really accepted nothing" — OSDI/ATC 2026 are simply not
    indexed by DBLP yet, which means something entirely different."""
    readme = render_readme(
        venues=["OSDI"], years=[2026], counts={}, updated="2026-08-12"
    )
    row = [line for line in readme.splitlines() if line.startswith("| 2026")][0]
    cells = [cell.strip() for cell in row.strip("|").split("|")]

    assert cells == ["2026", "—"]


def test_dblp_disambiguation_suffix_stripped_from_display():
    """DBLP appends a four-digit suffix to duplicate names ("Song Yu 0004").
    It is on 22.8% of the 12518 author entries here and is noise in a list for
    people; every suffixed entry also has a pid, so dropping it for display
    loses no identity and the JSON keeps DBLP's canonical form."""
    paper = Paper(
        title="T",
        authors=[Author(name="Song Yu 0004", pid="1/2"), Author(name="Jianliang Xu")],
        venue="VLDB",
        year=2026,
    )

    markdown = render_venue_year("VLDB", 2026, [paper], None, "2026-08-12")

    assert "Song Yu, Jianliang Xu" in markdown
    assert "0004" not in markdown


def test_year_like_trailing_number_in_title_is_untouched():
    """Only a trailing four-digit group on a name is stripped; years and numbers
    elsewhere are untouched."""
    from csconf.render import display_name

    assert display_name("Chenhao Ma 0001") == "Chenhao Ma"
    assert display_name("Jianliang Xu") == "Jianliang Xu"
    # Four digits that are not a disambiguation suffix must survive
    assert display_name("Deep Learning 2020 Team") == "Deep Learning 2020 Team"


def test_matched_links_are_marked_with_their_host():
    """A link matched by title is not an official page, so where it lands has to
    be visible at a glance. Sitting among official DBLP links and looking
    identical to them is the dishonest option."""
    papers = [
        Paper(
            title="Matched Paper", authors=[], venue="SOSP", year=2026,
            url="https://arxiv.org/abs/2605.15617", url_source="semanticscholar",
        ),
        Paper(
            title="Official Paper", authors=[], venue="SOSP", year=2026,
            url="https://www.usenix.org/conference/osdi26/presentation/x",
        ),
    ]

    out = render_venue_year("SOSP", 2026, papers, None, "2026-08-12")

    assert "- [Matched Paper](https://arxiv.org/abs/2605.15617) · arxiv.org" in out
    assert (
        "- [Official Paper](https://www.usenix.org/conference/osdi26/presentation/x)\n"
        in out
    )


def test_readme_states_where_links_come_from():
    out = render_readme(["SOSP"], [2026], {("SOSP", 2026): 1}, "2026-08-12")

    assert "Semantic Scholar" in out


def test_pdf_link_is_rendered_next_to_the_title():
    papers = [
        Paper(
            title="Open Paper", authors=[], venue="OSDI", year=2026,
            url="https://www.usenix.org/conference/osdi26/presentation/yu-shan",
            pdf_url="https://www.usenix.org/system/files/osdi26-yu-shan.pdf",
            pdf_source="usenix-derived",
        ),
    ]

    out = render_venue_year("OSDI", 2026, papers, None, "2026-08-12")

    assert (
        "- [Open Paper](https://www.usenix.org/conference/osdi26/presentation/yu-shan)"
        " · [PDF](https://www.usenix.org/system/files/osdi26-yu-shan.pdf)" in out
    )


def test_publisher_pdf_is_not_flagged_as_restricted():
    """The ACM Digital Library is open access, so a dl.acm.org PDF is as free to
    read as a USENIX one. An earlier version labelled these "PDF (ACM)" to warn
    about a paywall that no longer exists. What still differs is that scripts
    get a 403 there, which is recorded in pdf_source, not shown to readers."""
    papers = [
        Paper(
            title="Paywalled", authors=[], venue="SOSP", year=2025,
            url="https://doi.org/10.1145/1", doi="10.1145/1",
            pdf_url="https://dl.acm.org/doi/pdf/10.1145/1", pdf_source="publisher-doi",
        ),
    ]

    out = render_venue_year("SOSP", 2025, papers, None, "2026-08-12")

    assert "· [PDF](https://dl.acm.org/doi/pdf/10.1145/1)" in out
    assert "PDF (ACM)" not in out


def test_paper_without_any_link_falls_back_to_a_scholar_search():
    """Even a paper that turns up nowhere else deserves an address that takes a
    reader to it."""
    papers = [Paper(title="No Links At All", authors=[], venue="SOSP", year=2026)]

    out = render_venue_year("SOSP", 2026, papers, None, "2026-08-12")

    assert "[No Links At All](https://scholar.google.com/scholar?q=" in out
    assert "· scholar.google.com" in out


def test_preprint_is_rendered_after_the_official_pdf():
    """The preprint sits beside the version of record, never in place of it, and
    is labelled so nobody mistakes it for the camera-ready."""
    papers = [
        Paper(
            title="Both", authors=[], venue="SOSP", year=2025,
            url="https://doi.org/10.1145/1", doi="10.1145/1",
            pdf_url="https://dl.acm.org/doi/pdf/10.1145/1", pdf_source="publisher-doi",
            arxiv_id="2601.05536",
        ),
    ]

    out = render_venue_year("SOSP", 2025, papers, None, "2026-08-13")

    assert (
        "- [Both](https://doi.org/10.1145/1)"
        " · [PDF](https://dl.acm.org/doi/pdf/10.1145/1)"
        " · [preprint](https://arxiv.org/abs/2601.05536)" in out
    )


def test_preprint_is_not_repeated_when_the_pdf_is_already_that_arxiv_paper():
    """SOSP 2026's matched papers already point at arXiv. Printing "preprint"
    next to a link that is the same preprint is noise."""
    papers = [
        Paper(
            title="Matched", authors=[], venue="SOSP", year=2026,
            url="https://arxiv.org/abs/2605.15617", url_source="semanticscholar",
            pdf_url="https://arxiv.org/pdf/2605.15617", pdf_source="arxiv-derived",
            arxiv_id="2605.15617",
        ),
    ]

    out = render_venue_year("SOSP", 2026, papers, None, "2026-08-13")

    assert "preprint" not in out
