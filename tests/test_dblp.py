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
    """Anything but exactly one front-matter record breaks an assumption about
    DBLP's structure, and that has to be loud rather than silent."""
    from csconf.dblp import count_proceedings_entries

    assert count_proceedings_entries(_read("dblp-conf-sosp-sosp2025.xml")) == 1


def test_journal_toc_drops_front_matter():
    papers = parse_toc(_read("dblp-journals-pvldb-pvldb19.xml"), venue="VLDB", year=2026)

    assert len(papers) == 135
    assert not any(p.title.lower().startswith("front matter") for p in papers)


def test_journal_paper_keeps_volume_issue_and_month():
    papers = parse_toc(_read("dblp-journals-pvldb-pvldb19.xml"), venue="VLDB", year=2026)
    first_issue = [p for p in papers if p.issue == "1"]

    assert first_issue, "vol 19 N1 should contain papers"
    sample = first_issue[0]
    assert sample.year == 2026
    assert sample.published_year == 2025
    assert sample.published_month == "September"
    assert sample.volume == "19"


def test_pacmmod_editorial_variants_all_dropped():
    """Three observed shapes — with a colon, with a comma after PACMMOD, and
    without a colon — all have to be recognised."""
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
    """PVLDB front matter links a PDF directly, and body papers carry non-DOI ee too."""
    papers = parse_toc(_read("dblp-journals-pvldb-pvldb19.xml"), venue="VLDB", year=2026)
    for paper in papers:
        if paper.url and not paper.url.startswith("https://doi.org/"):
            assert paper.doi is None


def test_titles_with_nested_markup_are_not_truncated():
    """DBLP titles contain typesetting tags such as <i>/<sub>/<sup>. Reading
    .text truncates at the first child tag, turning "B<sub>2</sub>Mark: ..."
    into "B". Twelve of the 380 records in PACMMOD volume 3 (3.2%) are
    affected, and no record-count assertion would ever notice."""
    papers = parse_toc(
        _read("dblp-journals-pacmmod-pacmmod3-trimmed.xml"), venue="SIGMOD", year=2026
    )
    titles = {p.title for p in papers}

    assert "B2Mark: A Blind and Buyer-Traceable Watermarking Scheme for Tabular Datasets" in titles
    assert "A Local Search Approach to Efficient (k,p)-Core Maintenance" in titles
    # None of the truncated fragments may survive
    assert "B" not in titles
    assert not any(t.endswith(" (") for t in titles)


def test_acm_doi_missing_its_slash_is_repaired():
    """DBLP really carries "10.11453786702" for SIGMOD 2026's "Task Cascades for
    Efficient Unstructured Data Processing" — the slash is missing at the
    source, verified against dblp.org's own API. Crossref registers the paper
    under 10.1145/3786702 with a matching title and volume/issue, so the repair
    recovers the real DOI rather than inventing one. Left alone it is a dead
    doi.org link and no PDF at all."""
    from csconf.dblp import repair_doi

    assert repair_doi("10.11453786702") == "10.1145/3786702"
    assert repair_doi("10.1145/3786702") == "10.1145/3786702"


def test_repair_only_touches_the_acm_prefix():
    """Every publisher numbers its own way. Splicing a slash into an IEEE or
    Springer DOI would turn a broken link into a confidently wrong one."""
    from csconf.dblp import repair_doi

    assert repair_doi("10.11095678") == "10.11095678"
    assert repair_doi("10.1007978311") == "10.1007978311"
    assert repair_doi("10.48550/arXiv.2601.05536") == "10.48550/arXiv.2601.05536"
    assert repair_doi(None) is None


def test_repaired_doi_flows_into_the_paper_and_its_url():
    """The url has to be repaired alongside the doi. Leaving ee untouched would
    publish a dead doi.org link next to a correct DOI field."""
    from csconf.dblp import parse_toc

    xml = (
        '<?xml version="1.0"?><dblp><article key="journals/pacmmod/X"><title>T.</title>'
        '<author>A B</author><volume>4</volume><number>1</number>'
        "<ee>https://doi.org/10.11453786702</ee></article></dblp>"
    )
    paper = parse_toc(xml, venue="SIGMOD", year=2026)[0]

    assert paper.doi == "10.1145/3786702"
    assert paper.url == "https://doi.org/10.1145/3786702"
