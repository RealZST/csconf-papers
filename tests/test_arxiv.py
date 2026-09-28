from pathlib import Path

import pytest

from csconf import arxiv

FIXTURES = Path(__file__).parent / "fixtures"


def _feed(entries: str = "", total: int = 0) -> str:
    return (
        '<feed xmlns="http://www.w3.org/2005/Atom"'
        ' xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">'
        "<opensearch:totalResults>{}</opensearch:totalResults>{}</feed>"
    ).format(total, entries)


def test_search_url_sorts_by_submission_date():
    url = arxiv.search_url("Chuan Wu", start=100, max_results=50)
    assert url.startswith("https://export.arxiv.org/api/query?")
    assert "search_query=au%3A%22Chuan+Wu%22" in url
    assert "sortBy=submittedDate" in url and "sortOrder=descending" in url
    assert "start=100" in url and "max_results=50" in url


def test_parse_feed_reads_entries_and_total():
    entries, total = arxiv.parse_feed((FIXTURES / "arxiv-feed.xml").read_text(encoding="utf-8"))
    assert total == 93
    assert [e.arxiv_id for e in entries] == ["2608.15224", "2609.17536", "2607.02333"]
    first = entries[0]
    assert first.published == "2026-08-15"
    assert first.authors == ["Che Shen", "Junwei Su", "Lingpeng Kong", "Chuan Wu"]
    assert first.primary_category == "cs.LG"
    multi_line = entries[2]  # its abstract spans two lines in the feed
    assert "\n" not in multi_line.abstract
    assert "semantic deviations. This paper presents" in multi_line.abstract


def test_parse_feed_fails_on_an_api_error():
    error = (
        "<entry><id>http://arxiv.org/api/errors#start_must_be_an_integer</id>"
        "<title>Error</title><summary>start must be an integer</summary></entry>"
    )
    with pytest.raises(ValueError, match="start_must_be_an_integer"):
        arxiv.parse_feed(_feed(error, total=1))


@pytest.mark.parametrize("body", [
    "<html><body>busy</body></html>",
    "Rate exceeded.",
    '<feed xmlns="http://www.w3.org/2005/Atom"><title>q</title></feed>',
])
def test_parse_feed_rejects_a_page_without_a_total(body):
    with pytest.raises(ValueError):
        arxiv.parse_feed(body)


def test_parse_feed_returns_the_total_with_an_empty_page():
    assert arxiv.parse_feed(_feed(total=250)) == ([], 250)


def test_arxiv_id_handles_old_style_ids():
    assert arxiv.arxiv_id_from_url("http://arxiv.org/abs/cs/0101001v2") == "cs/0101001"
    assert arxiv.arxiv_id_from_url("http://arxiv.org/abs/2609.27040v1") == "2609.27040"


def test_author_block_extracts_affiliations():
    block = arxiv.author_block((FIXTURES / "arxiv-html-authors.html").read_text(encoding="utf-8"))
    assert "The University of Hong Kong" in block
    assert "<" not in block and "abstract" not in block


def test_author_block_missing_returns_none():
    assert arxiv.author_block("<html><body>no authors here</body></html>") is None


def test_author_block_accepts_extra_classes():
    html = '<div class="ltx_authors ltx_authors_1line">A B HKU</div><div class="ltx_abstract">x</div>'
    assert arxiv.author_block(html) == "A B HKU"


def test_author_block_without_abstract_stops_at_the_body():
    html = (
        '<div class="ltx_authors">Chuan Wu Elsewhere U</div>'
        '<section class="ltx_section"><p>We thank The University of Hong Kong</p></section>'
    )
    block = arxiv.author_block(html)
    assert block == "Chuan Wu Elsewhere U" and "Hong Kong" not in block


def test_author_block_without_any_end_marker_is_none():
    assert arxiv.author_block('<div class="ltx_authors">A B</div><p>The University of Hong Kong</p>') is None


def test_author_block_decodes_entities():
    html = '<div class="ltx_authors">Texas A&amp;M University</div><div class="ltx_abstract">x</div>'
    assert arxiv.author_block(html) == "Texas A&M University"
