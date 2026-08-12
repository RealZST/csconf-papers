import json

import pytest

from csconf import enrich
from csconf.models import Author, Paper


def _paper(title, authors, url=None):
    return Paper(
        title=title,
        authors=[Author(name=n) for n in authors],
        venue="SOSP",
        year=2026,
        url=url,
        source="sosp-web",
    )


def _match_response(title, authors, external_ids=None, oa_pdf=None):
    return json.dumps(
        {
            "data": [
                {
                    "title": title,
                    "authors": [{"name": n} for n in authors],
                    "externalIds": external_ids or {},
                    "openAccessPdf": {"url": oa_pdf} if oa_pdf else None,
                }
            ]
        }
    )


class FakeFetcher:
    """Replays responses in call order; queued exceptions are raised, for 404s and
    rate limiting."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_prefers_arxiv_abs_over_doi_and_pdf():
    """The arXiv abs page is the one a person wants: abstract, every version,
    and the PDF. A direct PDF or a doi.org redirect is worse."""
    record = enrich.MatchRecord(
        title="T",
        authors=["A B"],
        arxiv="2605.15617",
        doi="10.48550/arXiv.2605.15617",
        open_access_pdf="https://arxiv.org/pdf/2605.15617",
    )

    assert enrich.choose_url(record) == "https://arxiv.org/abs/2605.15617"


def test_falls_back_to_open_access_pdf_then_doi():
    assert (
        enrich.choose_url(
            enrich.MatchRecord("T", [], None, "10.1145/1", "https://x.org/p.pdf")
        )
        == "https://x.org/p.pdf"
    )
    assert (
        enrich.choose_url(enrich.MatchRecord("T", [], None, "10.1145/1", None))
        == "https://doi.org/10.1145/1"
    )
    assert enrich.choose_url(enrich.MatchRecord("T", [], None, None, None)) is None


def test_accepts_match_when_title_drifted_but_authors_agree():
    """SOSP 2026 accepted "...with CrystalLLM"; on arXiv it is "...with
    PrismLLM". Systems get renamed between submission and camera-ready all the
    time, and requiring identical titles would drop every such paper."""
    paper = _paper(
        "A Few GPUs, A Whole Lotta Scale: Faithful LLM Training Emulation with CrystalLLM",
        ["Shaoke Xi", "ChonLam Lao", "Boyi Jia"],
    )
    record = enrich.MatchRecord(
        title="A Few GPUs, A Whole Lotta Scale: Faithful LLM Training Emulation with PrismLLM",
        authors=["Shaoke Xi", "ChonLam Lao", "Boyi Jia"],
        arxiv="2605.15617",
        doi=None,
        open_access_pdf=None,
    )

    assert enrich.is_confident(paper, record)


def test_rejects_match_with_similar_title_but_unrelated_authors():
    """Fuzzy matching returns a different paper with a colliding title just as
    readily. A wrong link in a public repository is worse than an empty field:
    empty is visibly empty, a wrong link looks perfectly fine."""
    paper = _paper("Fast Consensus for Wide-Area Storage", ["Ann Lee", "Bob Ray"])
    record = enrich.MatchRecord(
        title="Fast Consensus for Wide Area Storage Systems",
        authors=["Carl Poe", "Dana Fox"],
        arxiv="2601.00001",
        doi=None,
        open_access_pdf=None,
    )

    assert not enrich.is_confident(paper, record)


def test_single_author_paper_matches_on_one_shared_surname():
    paper = _paper("Some Retitled Work", ["Ann Lee"])
    record = enrich.MatchRecord("Some Work, Retitled", ["Ann Lee"], "2601.2", None, None)

    assert enrich.is_confident(paper, record)


def test_exact_title_accepted_even_without_author_metadata():
    """Semantic Scholar sometimes returns no authors. An identical title should
    not be thrown away over the other side's missing metadata."""
    paper = _paper("Cohort: Decentralized PIR", ["Ann Lee", "Bob Ray"])
    record = enrich.MatchRecord("Cohort: Decentralized PIR.", [], None, "10.1145/9", None)

    assert enrich.is_confident(paper, record)


def test_lookup_returns_url_for_confident_match():
    fetcher = FakeFetcher(
        [
            _match_response(
                "Anchor: Mitigating Shallow Disruptions",
                ["Ann Lee", "Bob Ray"],
                {"ArXiv": "2604.09999"},
            )
        ]
    )
    paper = _paper("Anchor: Mitigating Shallow Disruptions", ["Ann Lee", "Bob Ray"])

    assert enrich.lookup(paper, fetcher).url == "https://arxiv.org/abs/2604.09999"
    assert "api.semanticscholar.org" in fetcher.urls[0]


def test_lookup_returns_none_when_not_found():
    """Semantic Scholar answers "no match" with a 404. That is an answer, not a
    fault."""
    from csconf.http import NotFound

    fetcher = FakeFetcher([NotFound("no match", 404)])

    outcome = enrich.lookup(_paper("Unpublished Work", ["Ann Lee"]), fetcher)

    assert outcome.url is None
    assert outcome.conclusive is True


def test_lookup_survives_rate_limiting():
    """Rate limiting must not break the run: this step is a bonus, and losing it
    only costs a link."""
    from csconf.http import RateLimited

    fetcher = FakeFetcher([RateLimited("429")])

    outcome = enrich.lookup(_paper("Anything", ["Ann Lee"]), fetcher)

    assert outcome.url is None
    assert outcome.conclusive is False


def test_enrich_only_queries_papers_without_url():
    """Papers that already have a link are never touched: an official page from
    DBLP always beats something a third party matched."""
    papers = [
        _paper("Has A Link", ["Ann Lee"], url="https://www.usenix.org/x"),
        _paper("Needs A Link", ["Bob Ray"]),
    ]
    fetcher = FakeFetcher([_match_response("Needs A Link", ["Bob Ray"], {"ArXiv": "1"})])

    enriched, cache, stats = enrich.enrich_papers(papers, cache={}, fetcher=fetcher, today="2026-08-12")

    assert len(fetcher.urls) == 1
    assert enriched[0].url == "https://www.usenix.org/x"
    assert enriched[0].url_source is None
    assert enriched[1].url == "https://arxiv.org/abs/1"
    assert enriched[1].url_source == "semanticscholar"
    assert stats["found"] == 1


def test_cache_hit_avoids_repeat_query():
    """sync rewrites each JSON in full every month, overwriting the links filled
    in here. The cache lives on disk of its own, or every month re-asks the API
    about the same papers."""
    paper = _paper("Cached Paper", ["Ann Lee"])
    cache = {paper.merge_key(): {"url": "https://arxiv.org/abs/2603.1", "source": "semanticscholar"}}
    fetcher = FakeFetcher([])

    enriched, cache, stats = enrich.enrich_papers([paper], cache=cache, fetcher=fetcher, today="2026-08-12")

    assert fetcher.urls == []
    assert enriched[0].url == "https://arxiv.org/abs/2603.1"
    assert stats["cached"] == 1


def test_recent_miss_is_not_requeried_but_stale_miss_is():
    """Misses are recorded too, or every month re-asks about the same papers
    that were not there. But not forever: papers appear on arXiv after the
    conference."""
    paper = _paper("Not Yet On arXiv", ["Ann Lee"])
    fresh = {paper.merge_key(): {"url": None, "checked": "2026-08-01"}}
    stale = {paper.merge_key(): {"url": None, "checked": "2026-01-01"}}

    _, _, stats = enrich.enrich_papers([paper], cache=fresh, fetcher=FakeFetcher([]), today="2026-08-12")
    assert stats["skipped_recent_miss"] == 1

    fetcher = FakeFetcher([_match_response("Not Yet On arXiv", ["Ann Lee"], {"ArXiv": "9"})])
    _, cache, stats = enrich.enrich_papers([paper], cache=stale, fetcher=fetcher, today="2026-08-12")
    assert len(fetcher.urls) == 1
    assert cache[paper.merge_key()]["url"] == "https://arxiv.org/abs/9"


def test_lookup_budget_caps_queries_per_run():
    """In CI this step shares a 45-minute budget with the sync, and the anonymous
    Semantic Scholar quota is shared with everyone else. Stop when it is spent;
    the rest waits for next month."""
    papers = [_paper("Paper {}".format(i), ["Ann Lee"]) for i in range(5)]
    fetcher = FakeFetcher([_match_response("Paper 0", ["Ann Lee"], {"ArXiv": "1"})] * 5)

    _, _, stats = enrich.enrich_papers(
        papers, cache={}, fetcher=fetcher, today="2026-08-12", budget=2
    )

    assert len(fetcher.urls) == 2
    assert stats["budget_exhausted"] is True


def test_rejected_match_is_cached_as_miss_not_retried_forever():
    paper = _paper("Distinct Title", ["Ann Lee"])
    fetcher = FakeFetcher([_match_response("Other Paper", ["Zed Poe"], {"ArXiv": "1"})])

    enriched, cache, stats = enrich.enrich_papers(
        [paper], cache={}, fetcher=fetcher, today="2026-08-12"
    )

    assert enriched[0].url is None
    assert cache[paper.merge_key()] == {"url": None, "checked": "2026-08-12"}
    assert stats["rejected"] == 1


def test_api_key_is_sent_when_configured(monkeypatch):
    """The anonymous pool is shared by every caller on the internet and we are
    measurably sitting at its limit: 429s throughout a 105-paper run. A key is
    free and lifts the limit, but it must stay optional — the repo has to work
    for anyone who clones it without one."""
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "secret")

    session = enrich.build_session()

    assert session.headers["x-api-key"] == "secret"
    assert "csconf-papers" in session.headers["User-Agent"]


def test_no_api_key_header_when_unset(monkeypatch):
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)

    session = enrich.build_session()

    assert "x-api-key" not in session.headers


def test_transient_failure_is_not_cached_as_a_miss():
    """A 404 means "no such title" and is worth remembering. Rate limiting means
    we never got to ask, and recording that as a miss would silence this paper
    for a whole quarter over a blip that lasted seconds."""
    from csconf.http import RateLimited

    paper = _paper("Never Actually Asked", ["Ann Lee"])
    fetcher = FakeFetcher([RateLimited("429")])

    _, cache, stats = enrich.enrich_papers(
        [paper], cache={}, fetcher=fetcher, today="2026-08-12"
    )

    assert paper.merge_key() not in cache
    assert stats["unavailable"] == 1


def test_definite_miss_is_still_cached():
    from csconf.http import NotFound

    paper = _paper("Genuinely Absent", ["Ann Lee"])
    fetcher = FakeFetcher([NotFound("no match", 404)])

    _, cache, _ = enrich.enrich_papers(
        [paper], cache={}, fetcher=fetcher, today="2026-08-12"
    )

    assert cache[paper.merge_key()] == {"url": None, "checked": "2026-08-12"}
