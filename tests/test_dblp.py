import json
from pathlib import Path

import pytest

from csconf.dblp import BadResponse, parse_stream_tocs, parse_toc

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _rows(*rows) -> str:
    """A SPARQL result document from handwritten binding rows."""
    return json.dumps({"head": {"vars": []}, "results": {"bindings": list(rows)}})


def _uri(value):
    return {"type": "uri", "value": value}


def _lit(value):
    return {"type": "literal", "value": value}


def test_conference_toc_counts_papers_only():
    """The proceedings front-matter record is neither Inproceedings nor Article,
    so the query's type filter keeps it out of the result at the server."""
    papers = parse_toc(
        _read("sparql-conf-sosp-sosp2025.json"), venue="SOSP", year=2025
    )

    assert len(papers) == 66
    assert not any("Proceedings of the ACM SIGOPS" in p.title for p in papers)


def test_conference_paper_fields_are_parsed():
    papers = parse_toc(
        _read("sparql-conf-sosp-sosp2025.json"), venue="SOSP", year=2025
    )
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


def test_author_order_follows_signature_ordinals():
    """Authorship order is the paper's byline order and must survive the
    grouping of one-row-per-signature results."""
    papers = parse_toc(
        _read("sparql-conf-sosp-sosp2025.json"), venue="SOSP", year=2025
    )
    dcp = next(p for p in papers if p.title.startswith("DCP"))

    assert [a.name for a in dcp.authors] == [
        "Chenyu Jiang 0002", "Zhenkun Cai", "Ye Tian", "Zhen Jia 0001",
        "Yida Wang 0003", "Chuan Wu 0001",
    ]


def test_journal_toc_drops_front_matter():
    papers = parse_toc(
        _read("sparql-journals-pvldb-pvldb19-trimmed.json"), venue="VLDB", year=2026
    )

    assert len(papers) == 30
    assert not any(p.title.lower().startswith("front matter") for p in papers)


def test_journal_paper_keeps_volume_issue_and_month():
    papers = parse_toc(
        _read("sparql-journals-pvldb-pvldb19-trimmed.json"), venue="VLDB", year=2026
    )
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
        _read("sparql-journals-pacmmod-pacmmod3-trimmed.json"), venue="SIGMOD", year=2026
    )

    assert not any("Editorial" in p.title for p in papers)


def test_is_non_paper_covers_each_editorial_format():
    from csconf.dblp import is_non_paper

    assert is_non_paper("PACMMOD V3, N1 (SIGMOD), February 2025: Editorial.")
    assert is_non_paper("PACMMOD, V3, N2 (PODS), May 2025 Editorial.")
    assert is_non_paper("PACMMOD V3, N5 (PODS), November 2025 Editorial.")
    assert is_non_paper("Front Matter.")
    assert not is_non_paper("B2Mark: A Blind and Buyer-Traceable Watermarking Scheme")


def test_non_doi_primary_page_leaves_doi_null_but_keeps_url():
    """PVLDB's primary document pages link vldb.org PDFs directly; the DOI
    field is only filled when the link itself is a doi.org one, as before."""
    papers = parse_toc(
        _read("sparql-journals-pvldb-pvldb19-trimmed.json"), venue="VLDB", year=2026
    )
    direct = [p for p in papers if p.url and not p.url.startswith("https://doi.org/")]

    assert direct, "the fixture should contain non-DOI primary pages"
    assert all(p.doi is None for p in direct)


def test_titles_arrive_as_plain_text():
    """DBLP titles contain typesetting markup in the XML exports
    ("B<sub>2</sub>Mark"); the RDF titles are already plain text. This pins
    that assumption against the real endpoint's data."""
    papers = parse_toc(
        _read("sparql-journals-pacmmod-pacmmod3-trimmed.json"), venue="SIGMOD", year=2026
    )
    titles = {p.title for p in papers}

    assert "B2Mark: A Blind and Buyer-Traceable Watermarking Scheme for Tabular Datasets" in titles
    assert "A Local Search Approach to Efficient (k,p)-Core Maintenance" in titles
    assert "B" not in titles


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
    """The url has to be repaired alongside the doi. Leaving the primary page
    untouched would publish a dead doi.org link next to a correct DOI field."""
    body = _rows(
        {
            "paper": _uri("https://dblp.org/rec/journals/pacmmod/X"),
            "title": _lit("T."),
            "volume": _lit("4"),
            "issue": _lit("1"),
            "primary": _uri("https://doi.org/10.11453786702"),
            "ord": _lit("1"),
            "name": _lit("A B"),
        }
    )
    paper = parse_toc(body, venue="SIGMOD", year=2026)[0]

    assert paper.doi == "10.1145/3786702"
    assert paper.url == "https://doi.org/10.1145/3786702"


def test_demo_and_poster_entries_are_not_papers():
    """MobiCom's DBLP TOC carries its demo track in the same proceedings: 80 of
    the 157 entries for 2025 are titled "Demo: ...". Those are not accepted
    papers, and the publisher labels them itself, so the prefix is a reliable
    signal rather than a guess."""
    from csconf.dblp import is_non_paper

    assert is_non_paper("Demo: Networked iGYM for AR Exergames")
    assert is_non_paper("Poster: Something Small")
    assert is_non_paper("POSTER: Shouting About It")
    assert is_non_paper("Abstract: A Talk")


def test_short_papers_are_papers():
    """SIGCOMM 2025 has a Short Papers section — 14 three-page entries with no
    prefix, sitting under that heading in DBLP's own TOC. They are peer-reviewed
    conference papers, so length is not a signal and only the explicit label is.
    """
    from csconf.dblp import is_non_paper

    assert not is_non_paper("Coflow Scheduling for LLM Training")
    assert not is_non_paper("Demonstrating Scalable Inference at Line Rate")
    assert not is_non_paper("Posterior Sampling for Network Tomography")


def test_empty_result_means_no_papers():
    """A TOC dblp does not have yet comes back as zero bindings, not as a 404
    the way the retired XML export answered."""
    assert parse_toc(_rows(), venue="OSDI", year=2026) == []


def test_html_body_raises_bad_response_with_a_hint():
    """This is exactly how dblp's bot protection broke the old fetch path: an
    HTTP 200 whose body is a challenge page. The error has to say what the
    body probably is, not just that JSON parsing failed."""
    challenge = "<!doctype html><html><head><title>Making sure you're not a bot!</title></head></html>"

    with pytest.raises(BadResponse, match="bot challenge"):
        parse_toc(challenge, venue="SOSP", year=2025)


def test_stream_tocs_parse_to_a_list_of_iris():
    tocs = parse_stream_tocs(_read("sparql-conf-asplos-tocs-trimmed.json"))

    assert "https://dblp.org/db/conf/asplos/asplos2025-1" in tocs
    assert all(t.startswith("https://dblp.org/db/conf/asplos/") for t in tocs)
