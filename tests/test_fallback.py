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
    """单位内联且含逗号：必须先剥 (...) 再按逗号切，否则
    "(University of California, Los Angeles)" 会被切成两个假作者。"""
    papers = parse_sigops_accepted(
        _read("sigops-sosp-2026-accepted.html"), venue="SOSP", year=2026
    )
    names = {a.name for p in papers for a in p.authors}

    assert not any("University" in n or "Los Angeles" == n for n in names)
    assert "Konstantinos Kallas" in names


def test_entities_are_decoded_so_merge_key_matches_dblp():
    """merge_key 不认识 &amp;。不解码的话，同一篇论文的 web 版与 dblp 版
    匹配不上，产生重复条目。"""
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
    """单位里还能再嵌括号。实测 SOSP 2026 有
    "(The Chinese University of Hong Kong (CUHK))" 和
    "(Wuhan National Laboratory for Optoelectronics (WNLO) of Huazhong
    University of Science and Technology (HUST))"。
    只剥一层会留下残片，再按逗号切就变成假作者名。
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
