import json

from csconf import preprint
from csconf.models import Paper


def _paper(title="T", doi=None, arxiv_id=None):
    return Paper(
        title=title, authors=[], venue="SOSP", year=2025, doi=doi, arxiv_id=arxiv_id
    )


def _batch_response(*records):
    """Semantic Scholar returns one slot per requested id, null when unknown."""
    return json.dumps(
        [
            None
            if r is None
            else {"title": r[0], "externalIds": {"ArXiv": r[1]} if r[1] else {}}
            for r in records
        ]
    )


class FakeBatch:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post_json(self, url, payload):
        self.calls.append(payload["ids"])
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_maps_results_by_position_not_by_returned_doi():
    """The batch endpoint answers with one slot per requested id, in order, and
    null for ids it does not know. Matching on the DOI it echoes back would be
    fragile — case and formatting are not guaranteed to survive the round trip,
    and a null slot carries no DOI at all to match on."""
    papers = [_paper("A", doi="10.1145/1"), _paper("B", doi="10.1145/2"), _paper("C", doi="10.1145/3")]
    fetcher = FakeBatch([_batch_response(("A", "2601.1"), None, ("C", "2601.3"))])

    filled, _, _ = preprint.fill_arxiv_ids(papers, cache={}, fetcher=fetcher, today="2026-08-13")

    assert [p.arxiv_id for p in filled] == ["2601.1", None, "2601.3"]


def test_only_papers_with_a_doi_are_looked_up():
    """A DOI is an exact identifier, so the arXiv id it maps to belongs to that
    exact paper. Without one we would be back to matching titles, which is how
    a wrong link gets published."""
    papers = [_paper("Has DOI", doi="10.1145/1"), _paper("No DOI")]
    fetcher = FakeBatch([_batch_response(("Has DOI", "2601.1"))])

    filled, _, stats = preprint.fill_arxiv_ids(papers, cache={}, fetcher=fetcher, today="2026-08-13")

    assert fetcher.calls == [["DOI:10.1145/1"]]
    assert filled[1].arxiv_id is None
    assert stats["found"] == 1


def test_existing_arxiv_id_is_never_requeried():
    papers = [_paper(doi="10.1145/1", arxiv_id="2601.9")]
    fetcher = FakeBatch([])

    filled, _, stats = preprint.fill_arxiv_ids(papers, cache={}, fetcher=fetcher, today="2026-08-13")

    assert fetcher.calls == []
    assert filled[0].arxiv_id == "2601.9"


def test_requests_are_chunked_at_the_endpoint_limit():
    """Semantic Scholar caps a batch at 500 ids. 977 ACM papers is two requests,
    which is the whole reason this runs by DOI instead of one query per title."""
    papers = [_paper("P{}".format(i), doi="10.1145/{}".format(i)) for i in range(501)]
    fetcher = FakeBatch(
        [
            _batch_response(*[("P{}".format(i), None) for i in range(500)]),
            _batch_response(("P500", "2601.500")),
        ]
    )

    filled, _, _ = preprint.fill_arxiv_ids(papers, cache={}, fetcher=fetcher, today="2026-08-13")

    assert [len(c) for c in fetcher.calls] == [500, 1]
    assert filled[500].arxiv_id == "2601.500"


def test_hit_and_miss_are_both_cached():
    papers = [_paper("A", doi="10.1145/1"), _paper("B", doi="10.1145/2")]
    fetcher = FakeBatch([_batch_response(("A", "2601.1"), ("B", None))])

    _, cache, _ = preprint.fill_arxiv_ids(papers, cache={}, fetcher=fetcher, today="2026-08-13")

    assert cache["10.1145/1"] == {"arxiv_id": "2601.1", "checked": "2026-08-13"}
    assert cache["10.1145/2"] == {"arxiv_id": None, "checked": "2026-08-13"}


def test_cached_entries_short_circuit_the_request():
    papers = [_paper("A", doi="10.1145/1"), _paper("B", doi="10.1145/2")]
    cache = {
        "10.1145/1": {"arxiv_id": "2601.1", "checked": "2026-08-13"},
        "10.1145/2": {"arxiv_id": None, "checked": "2026-08-13"},
    }
    fetcher = FakeBatch([])

    filled, _, stats = preprint.fill_arxiv_ids(
        papers, cache=cache, fetcher=fetcher, today="2026-08-13"
    )

    assert fetcher.calls == []
    assert filled[0].arxiv_id == "2601.1"
    assert stats["cached"] == 1


def test_stale_miss_is_retried():
    """A paper can reach arXiv after its camera-ready, so a miss is not forever."""
    papers = [_paper("A", doi="10.1145/1")]
    cache = {"10.1145/1": {"arxiv_id": None, "checked": "2026-01-01"}}
    fetcher = FakeBatch([_batch_response(("A", "2601.1"))])

    filled, _, _ = preprint.fill_arxiv_ids(
        papers, cache=cache, fetcher=fetcher, today="2026-08-13"
    )

    assert filled[0].arxiv_id == "2601.1"


def test_a_failed_request_caches_nothing_and_does_not_raise():
    """Same rule as the title lookups: a 429 means we never got to ask, and
    recording that as "no preprint" would suppress the whole batch for a
    quarter over a blip."""
    from csconf.http import RateLimited

    papers = [_paper("A", doi="10.1145/1")]
    fetcher = FakeBatch([RateLimited("429")])

    filled, cache, stats = preprint.fill_arxiv_ids(
        papers, cache={}, fetcher=fetcher, today="2026-08-13"
    )

    assert filled[0].arxiv_id is None
    assert cache == {}
    assert stats["unavailable"] == 1


def test_budget_counts_requests_not_papers():
    papers = [_paper("P{}".format(i), doi="10.1145/{}".format(i)) for i in range(501)]
    fetcher = FakeBatch([_batch_response(*[("P{}".format(i), None) for i in range(500)])])

    _, _, stats = preprint.fill_arxiv_ids(
        papers, cache={}, fetcher=fetcher, today="2026-08-13", budget=1
    )

    assert len(fetcher.calls) == 1
    assert stats["budget_exhausted"] is True


def test_malformed_payload_is_survivable():
    papers = [_paper("A", doi="10.1145/1")]
    fetcher = FakeBatch(["not json at all"])

    filled, cache, stats = preprint.fill_arxiv_ids(
        papers, cache={}, fetcher=fetcher, today="2026-08-13"
    )

    assert filled[0].arxiv_id is None
    assert cache == {}
    assert stats["unavailable"] == 1


def test_short_response_does_not_misalign_the_rest():
    """If the endpoint ever returns fewer slots than ids, positional mapping
    would silently attach the wrong arXiv id to every paper after the gap.
    Refuse the batch instead."""
    papers = [_paper("A", doi="10.1145/1"), _paper("B", doi="10.1145/2")]
    fetcher = FakeBatch([_batch_response(("A", "2601.1"))])

    filled, cache, stats = preprint.fill_arxiv_ids(
        papers, cache={}, fetcher=fetcher, today="2026-08-13"
    )

    assert [p.arxiv_id for p in filled] == [None, None]
    assert cache == {}
    assert stats["unavailable"] == 1
