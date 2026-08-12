from pathlib import Path

from csconf.dblp import parse_toc

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_conference_toc_drops_proceedings_entry():
    papers = parse_toc(_read("dblp-conf-sosp-sosp2025.xml"), venue="SOSP", year=2025)

    assert len(papers) == 66
    assert not any("Proceedings of the ACM SIGOPS" in p.title for p in papers)


def test_conference_paper_fields_are_parsed():
    papers = parse_toc(_read("dblp-conf-sosp-sosp2025.xml"), venue="SOSP", year=2025)
    lithos = next(p for p in papers if p.title.startswith("LithOS"))

    assert lithos.title == "LithOS: An Operating System for Efficient Machine Learning on GPUs"
    assert lithos.venue == "SOSP"
    assert lithos.year == 2025
    assert lithos.published_year == 2025
    assert lithos.pages == "1-17"
    assert lithos.doi == "10.1145/3731569.3764818"
    assert lithos.url == "https://doi.org/10.1145/3731569.3764818"
    assert lithos.dblp_paper_key == "conf/sosp/CoppockZSKYSSM025"
    assert lithos.authors[0].name == "Patrick H. Coppock"
    assert lithos.authors[0].pid == "405/6876"
    assert lithos.authors[0].orcid == "0000-0002-7101-6961"
    assert lithos.published_month is None
    assert lithos.volume is None
    assert lithos.issue is None


def test_conference_toc_asserts_exactly_one_proceedings_entry():
    """前言条目数不为 1 意味着对 DBLP 结构的假设失效，必须炸而不是静默。"""
    from csconf.dblp import count_proceedings_entries

    assert count_proceedings_entries(_read("dblp-conf-sosp-sosp2025.xml")) == 1


def test_journal_toc_drops_front_matter():
    papers = parse_toc(_read("dblp-journals-pvldb-pvldb19.xml"), venue="VLDB", year=2026)

    assert len(papers) == 135
    assert not any(p.title.lower().startswith("front matter") for p in papers)


def test_journal_paper_keeps_volume_issue_and_month():
    papers = parse_toc(_read("dblp-journals-pvldb-pvldb19.xml"), venue="VLDB", year=2026)
    first_issue = [p for p in papers if p.issue == "1"]

    assert first_issue, "vol 19 N1 应有论文"
    sample = first_issue[0]
    assert sample.year == 2026
    assert sample.published_year == 2025
    assert sample.published_month == "September"
    assert sample.volume == "19"


def test_pacmmod_editorial_variants_all_dropped():
    """三种实测格式：带冒号 / PACMMOD 后带逗号 / 缺冒号，必须全部识别。"""
    papers = parse_toc(
        _read("dblp-journals-pacmmod-pacmmod3-trimmed.xml"), venue="SIGMOD", year=2026
    )

    assert not any("Editorial" in p.title for p in papers)


def test_is_non_paper_covers_each_editorial_format():
    from csconf.dblp import is_non_paper

    assert is_non_paper("PACMMOD V3, N1 (SIGMOD), February 2025: Editorial.")
    assert is_non_paper("PACMMOD, V3, N2 (PODS), May 2025 Editorial.")
    assert is_non_paper("PACMMOD V3, N5 (PODS), November 2025 Editorial.")
    assert is_non_paper("Front Matter.")
    assert not is_non_paper("B2Mark: A Blind and Buyer-Traceable Watermarking Scheme")


def test_non_doi_ee_leaves_doi_null_but_keeps_url():
    """PVLDB 的 Front Matter 用 PDF 直链；正文论文中也存在非 DOI 的 ee。"""
    papers = parse_toc(_read("dblp-journals-pvldb-pvldb19.xml"), venue="VLDB", year=2026)
    for paper in papers:
        if paper.url and not paper.url.startswith("https://doi.org/"):
            assert paper.doi is None


def test_titles_with_nested_markup_are_not_truncated():
    """DBLP 标题里会出现 <i>/<sub>/<sup> 排版标签。用 .text 取值会在第一个
    子标签处截断——"B<sub>2</sub>Mark: ..." 变成 "B"。实测 PACMMOD vol 3
    的 380 条记录中 12 条（3.2%）受影响，条数断言完全察觉不到。"""
    papers = parse_toc(
        _read("dblp-journals-pacmmod-pacmmod3-trimmed.xml"), venue="SIGMOD", year=2026
    )
    titles = {p.title for p in papers}

    assert "B2Mark: A Blind and Buyer-Traceable Watermarking Scheme for Tabular Datasets" in titles
    assert "A Local Search Approach to Efficient (k,p)-Core Maintenance" in titles
    # 截断后的残片不得出现
    assert "B" not in titles
    assert not any(t.endswith(" (") for t in titles)
