from pathlib import Path

from csconf.fallback import parse_sigops_accepted, parse_usenix_sessions

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_usenix_extracts_papers_and_drops_keynote():
    papers = parse_usenix_sessions(
        _read("usenix-osdi-2026-accepted.html"), venue="OSDI", year=2026
    )

    assert len(papers) == 5
    assert not any("Analysis for Better Resilience" == p.title for p in papers)
    assert all(p.source == "osdi-web" for p in papers)
    assert all(p.year == 2026 for p in papers)
    assert all(p.doi is None and p.dblp_paper_key is None for p in papers)
    assert all(p.title for p in papers)


def test_usenix_keeps_presentation_url():
    """The href on the title is already read to filter out the keynote, and
    keeping it gives the paper's own page. Dropping it leaves a whole edition
    without links whenever the site fallback is used (OSDI 2026), while the
    same conference has one per paper for 2025 via DBLP — two shapes in one
    listing."""
    papers = parse_usenix_sessions(
        _read("usenix-osdi-2026-accepted.html"), venue="OSDI", year=2026
    )

    assert all(
        p.url and p.url.startswith("https://www.usenix.org/conference/osdi26/presentation/")
        for p in papers
    )


def test_sigops_extracts_titles_and_authors():
    papers = parse_sigops_accepted(
        _read("sigops-sosp-2026-accepted.html"), venue="SOSP", year=2026
    )

    assert len(papers) == 6
    assert all(p.source == "sosp-web" for p in papers)
    titles = {p.title for p in papers}
    assert (
        "A Few GPUs, A Whole Lotta Scale: Faithful LLM Training Emulation with CrystalLLM"
        in titles
    )


def test_affiliation_commas_do_not_become_authors():
    """Affiliations are inline and contain commas, so parentheses have to come
    off before splitting or "(University of California, Los Angeles)" becomes
    two authors who do not exist."""
    papers = parse_sigops_accepted(
        _read("sigops-sosp-2026-accepted.html"), venue="SOSP", year=2026
    )
    names = {a.name for p in papers for a in p.authors}

    assert not any("University" in n or "Los Angeles" == n for n in names)
    assert "Konstantinos Kallas" in names


def test_entities_are_decoded_so_merge_key_matches_dblp():
    """merge_key does not know &amp;. Without decoding, a paper's web record
    never matches its DBLP record and the entry is duplicated."""
    from csconf.models import Paper

    html = (
        '<ul class="paperlist"><li><b>Experiments &amp; Analysis</b><br />'
        "<em>Ann Lee (Somewhere)</em></li></ul>"
    )
    web = parse_sigops_accepted(html, venue="SOSP", year=2026)[0]
    dblp = Paper(title="Experiments & Analysis", authors=[], venue="SOSP", year=2026)

    assert web.title == "Experiments & Analysis"
    assert web.merge_key() == dblp.merge_key()


def test_trailing_period_stripped_to_match_dblp_titles():
    html = (
        '<ul class="paperlist"><li><b>Some Paper Title.</b><br />'
        "<em>Ann Lee (Somewhere)</em></li></ul>"
    )
    paper = parse_sigops_accepted(html, venue="SOSP", year=2026)[0]

    assert paper.title == "Some Paper Title"


def test_nested_affiliation_parentheses_fully_stripped():
    """Affiliations nest parentheses of their own. SOSP 2026 contains
    "(The Chinese University of Hong Kong (CUHK))" and
    "(Wuhan National Laboratory for Optoelectronics (WNLO) of Huazhong
    University of Science and Technology (HUST))".
    Stripping one level leaves shards that split into authors who do not exist.
    """
    html = (
        '<ul class="paperlist"><li><b>P</b><br /><em>'
        "Ming-Chang Yang (The Chinese University of Hong Kong (CUHK)), "
        "Ke Zhou (Wuhan National Laboratory for Optoelectronics (WNLO) of "
        "Huazhong University of Science and Technology (HUST)), "
        "Jie Zhang (Peking University)"
        "</em></li></ul>"
    )

    names = [a.name for a in parse_sigops_accepted(html, venue="SOSP", year=2026)[0].authors]

    assert names == ["Ming-Chang Yang", "Ke Zhou", "Jie Zhang"]
    assert not any("(" in n or ")" in n for n in names)


def test_commented_out_paperlist_is_ignored():
    """The SIGOPS SOSP 2026 page keeps the previous edition's list in the source,
    wrapped in an HTML comment. A regex parser does not know what a comment is,
    so it read 43 SOSP 2024 papers as SOSP 2026 ones — 38 of the 43 match the
    DBLP SOSP 2024 TOC exactly, and none of the 62 live ones do. Stripping
    comments before parsing is the whole fix."""
    html = (
        '<ul class="paperlist"><li><b>Real 2026 Paper</b><br />'
        "<em>Ann Lee (Somewhere)</em></li></ul>"
        "<!--\n"
        '<ul class="paperlist"><li><b>Stale 2024 Paper</b><br />'
        "<em>Bob Ray (Elsewhere)</em></li></ul>\n"
        "-->"
    )

    papers = parse_sigops_accepted(html, venue="SOSP", year=2026)

    assert [p.title for p in papers] == ["Real 2026 Paper"]


def test_commented_out_usenix_article_is_ignored():
    """Same hazard on the USENIX side: the parser splits on <article, which a
    comment would not stop either."""
    live = (
        '<article><h2><a href="/conference/osdi26/presentation/lee">Live Paper</a></h2></article>'
    )
    html = live + "<!-- " + live.replace("Live Paper", "Commented Paper").replace(
        "/lee", "/ray"
    ) + " -->"

    papers = parse_usenix_sessions(html, venue="OSDI", year=2026)

    assert [p.title for p in papers] == ["Live Paper"]
