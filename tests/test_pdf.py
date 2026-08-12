import pytest

from csconf import pdf
from csconf.models import Paper


def _paper(url=None, doi=None, title="T"):
    return Paper(title=title, authors=[], venue="OSDI", year=2026, url=url, doi=doi)


def test_url_that_is_already_a_pdf_is_used_as_is():
    """PVLDB's ee points straight at a PDF, so 618 papers cost no request."""
    paper = _paper(url="https://www.vldb.org/pvldb/vol18/p1-arch.pdf")

    assert pdf.derive(paper) == ("https://www.vldb.org/pvldb/vol18/p1-arch.pdf", "source")


def test_usenix_presentation_page_derives_system_files_pdf():
    """A USENIX PDF address follows from the presentation URL, which carries both
    the conference tag and the slug. A spot check of 12 across OSDI 25/26,
    NSDI 25 and ATC 25 returned 200 application/pdf every time."""
    paper = _paper(url="https://www.usenix.org/conference/osdi26/presentation/yu-shan")

    assert pdf.derive(paper) == (
        "https://www.usenix.org/system/files/osdi26-yu-shan.pdf",
        "usenix-derived",
    )


def test_usenix_derivation_needs_verification_flag():
    """A derived address is a guess and has to be checked before it goes into a
    public listing, so the source marker must separate "derived, unverified"
    from "handed to us"."""
    assert pdf.needs_verification("usenix-derived") is True
    assert pdf.needs_verification("source") is False
    assert pdf.needs_verification("publisher-doi") is False


def test_acm_doi_derives_publisher_pdf():
    """A dl.acm.org PDF address is built straight from the DOI with no request.
    Whether it downloads depends on the paper being open access, which the
    source marker records rather than passing it off as free full text."""
    paper = _paper(url="https://doi.org/10.1145/3731569.3764818", doi="10.1145/3731569.3764818")

    assert pdf.derive(paper) == (
        "https://dl.acm.org/doi/pdf/10.1145/3731569.3764818",
        "publisher-doi",
    )


def test_paper_without_url_or_doi_has_no_derivable_pdf():
    assert pdf.derive(_paper()) == (None, None)


def test_arxiv_abs_url_derives_pdf():
    paper = _paper(url="https://arxiv.org/abs/2605.15617")

    assert pdf.derive(paper) == ("https://arxiv.org/pdf/2605.15617", "arxiv-derived")


def test_doi_org_link_that_is_not_acm_yields_nothing():
    """Only ACM DOIs build a PDF address; other publishers use different paths,
    and applying this one blindly produces a link that 404s."""
    paper = _paper(url="https://doi.org/10.1109/1", doi="10.1109/1")

    assert pdf.derive(paper) == (None, None)


def test_scholar_search_url_is_built_from_title():
    """With no source link at all, give at least an address that finds the paper.
    This is a constructed search URL; Scholar is never fetched, since its
    robots.txt disallows /scholar."""
    url = pdf.scholar_search_url("Prism: Cost-Efficient Multi-LLM Serving")

    assert url.startswith("https://scholar.google.com/scholar?q=")
    assert "Prism" in url
    assert " " not in url


class FakeHead:
    def __init__(self, results):
        self.results = dict(results)
        self.checked = []

    def head(self, url):
        self.checked.append(url)
        return self.results.get(url, False)


def test_verification_keeps_only_urls_that_serve_a_pdf():
    good = "https://www.usenix.org/system/files/osdi26-yu-shan.pdf"
    bad = "https://www.usenix.org/system/files/osdi26-nobody.pdf"
    checker = FakeHead({good: True, bad: False})

    assert pdf.verify(good, checker.head, cache={}) == (True, {good: True})
    assert pdf.verify(bad, checker.head, cache={}) == (False, {bad: False})


def test_verification_result_is_cached_so_ci_checks_each_pdf_once():
    """Re-checking two thousand papers every month is waste, and usenix.org has
    already blocked us once for repeated requests."""
    url = "https://www.usenix.org/system/files/osdi26-yu-shan.pdf"
    checker = FakeHead({})

    ok, cache = pdf.verify(url, checker.head, cache={url: True})

    assert ok is True
    assert checker.checked == []


def test_fill_pdfs_derives_and_verifies_only_what_is_missing():
    papers = [
        _paper(url="https://www.vldb.org/pvldb/vol18/p1-arch.pdf"),
        _paper(url="https://www.usenix.org/conference/osdi26/presentation/yu-shan"),
        _paper(url="https://doi.org/10.1145/1", doi="10.1145/1"),
        _paper(),
    ]
    checker = FakeHead({"https://www.usenix.org/system/files/osdi26-yu-shan.pdf": True})

    filled, cache, stats = pdf.fill_pdfs(papers, cache={}, head=checker.head)

    assert [p.pdf_url for p in filled] == [
        "https://www.vldb.org/pvldb/vol18/p1-arch.pdf",
        "https://www.usenix.org/system/files/osdi26-yu-shan.pdf",
        "https://dl.acm.org/doi/pdf/10.1145/1",
        None,
    ]
    # Only the derived USENIX URL is a guess, so it is the only one worth a request.
    assert checker.checked == ["https://www.usenix.org/system/files/osdi26-yu-shan.pdf"]
    assert stats["filled"] == 3


def test_failed_verification_leaves_the_paper_without_a_pdf_link():
    """A guessed URL that does not serve a PDF is worse than no link: it looks
    exactly like a working one until someone clicks it."""
    papers = [_paper(url="https://www.usenix.org/conference/osdi26/presentation/ghost")]
    checker = FakeHead({})

    filled, cache, stats = pdf.fill_pdfs(papers, cache={}, head=checker.head)

    assert filled[0].pdf_url is None
    assert stats["unverified"] == 1
    assert cache["https://www.usenix.org/system/files/osdi26-ghost.pdf"] is False


def test_existing_pdf_links_are_left_alone():
    papers = [_paper(url="https://x.org/a")]
    papers[0].pdf_url = "https://x.org/already.pdf"
    checker = FakeHead({})

    filled, _, stats = pdf.fill_pdfs(papers, cache={}, head=checker.head)

    assert filled[0].pdf_url == "https://x.org/already.pdf"
    assert stats["filled"] == 0


def test_verification_budget_stops_requests_but_keeps_free_derivations():
    """HEAD checks share the CI run's time budget with the sync. Running out of
    budget must not stop the derivations that need no request at all."""
    usenix = [
        _paper(url="https://www.usenix.org/conference/osdi26/presentation/p{}".format(i))
        for i in range(4)
    ]
    free = _paper(url="https://doi.org/10.1145/1", doi="10.1145/1")
    checker = FakeHead(
        {"https://www.usenix.org/system/files/osdi26-p{}.pdf".format(i): True for i in range(4)}
    )

    filled, _, stats = pdf.fill_pdfs(usenix + [free], cache={}, head=checker.head, budget=2)

    assert len(checker.checked) == 2
    assert stats["budget_exhausted"] is True
    assert filled[-1].pdf_url == "https://dl.acm.org/doi/pdf/10.1145/1"


def test_spent_budget_does_not_block_derivations_that_need_no_request():
    """The real run stopped after SOSP 2026 spent the lookup budget, and VLDB
    2026's 135 papers were left without PDF links — even though every one of
    them was a free derivation from a url that already pointed at a PDF."""
    papers = [_paper(url="https://www.vldb.org/pvldb/vol19/p1-x.pdf")]

    filled, _, stats = pdf.fill_pdfs(papers, cache={}, head=FakeHead({}).head, budget=0)

    assert filled[0].pdf_url == "https://www.vldb.org/pvldb/vol19/p1-x.pdf"
    assert stats["filled"] == 1
