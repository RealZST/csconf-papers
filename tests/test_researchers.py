import json
from dataclasses import replace

import pytest

from csconf import arxiv, dblp
from csconf.http import HttpError, NotFound
from csconf.models import Researcher
from csconf.researchers import collect, load_researchers, merge_feed, sync_researcher

SCHOOLS_LINE = "    schools: ['\\bPKU\\b', 'Peking University']\n"

YAML = """\
researchers:
  - slug: xin-jin
    name: Xin Jin
    dblp_pid: 68/3340-8
    affiliation: Peking University
    known_for: Programmable networks
    match: strict
""" + SCHOOLS_LINE


def _load(tmp_path, text):
    path = tmp_path / "researchers.yaml"
    path.write_text(text, encoding="utf-8")
    return load_researchers(str(path))


def _edited(old, new):
    """YAML with one edit applied. Asserts the edit took, so a rejection test
    cannot pass on a replace that silently did nothing."""
    edited = YAML.replace(old, new)
    assert edited != YAML
    return edited


def test_loads_researchers(tmp_path):
    [r] = _load(tmp_path, YAML)
    assert r == Researcher(
        slug="xin-jin", name="Xin Jin", dblp_pid="68/3340-8",
        affiliation="Peking University", known_for="Programmable networks",
        match="strict", schools=["\\bPKU\\b", "Peking University"],
    )


def test_empty_known_for_loads_as_empty_string(tmp_path):
    [r] = _load(tmp_path, _edited("known_for: Programmable networks", "known_for:"))
    assert r.known_for == ""


def test_school_modes_need_schools(tmp_path):
    with pytest.raises(ValueError, match="xin-jin"):
        _load(tmp_path, _edited(SCHOOLS_LINE, ""))


def test_unknown_match_mode_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="xin-jin"):
        _load(tmp_path, _edited("match: strict", "match: fuzzy"))


def test_schools_as_a_bare_string_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="xin-jin"):
        _load(tmp_path, _edited(SCHOOLS_LINE, "    schools: 'Peking University'\n"))


def test_uncompilable_school_pattern_is_rejected(tmp_path):
    with pytest.raises(ValueError, match=r"xin-jin.*'\(PKU'"):
        _load(tmp_path, _edited(SCHOOLS_LINE, "    schools: ['(PKU']\n"))


def test_duplicate_slug_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="xin-jin: duplicate slug"):
        _load(tmp_path, YAML + YAML.split("researchers:\n", 1)[1])


# --- collect / sync_researcher ---------------------------------------------

SINCE = "2026-06-01"
CHUAN_WU = Researcher(
    slug="chuan-wu", name="Chuan Wu", dblp_pid="34/3772-1", affiliation="HKU",
    known_for="", match="school", schools=["\\bHKU\\b"],
)
AUTHORS = ["Alice Smith", "Chuan Wu", "Bob Lee"]


class StubFetcher:
    """A canned body, or an exception to raise, per URL; any other URL is a
    404, as for a paper without HTML."""

    def __init__(self, mapping):
        self.mapping = mapping
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        body = self.mapping.get(url, NotFound("no stub for " + url, 404))
        if isinstance(body, Exception):
            raise body
        return body


def _entry(arxiv_id, published="2026-09-01", authors=AUTHORS):
    names = "".join("<author><name>{}</name></author>".format(a) for a in authors)
    return (
        "<entry><id>http://arxiv.org/abs/{0}v1</id><title>Paper {0}</title>"
        "<summary>About {0}</summary><published>{1}T12:00:00Z</published>{2}"
        '<arxiv:primary_category term="cs.DC"/></entry>'
    ).format(arxiv_id, published, names)


def _feed(entries, total, start=0):
    return (
        '<feed xmlns="http://www.w3.org/2005/Atom"'
        ' xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"'
        ' xmlns:arxiv="http://arxiv.org/schemas/atom">'
        "<opensearch:totalResults>{}</opensearch:totalResults>"
        "<opensearch:startIndex>{}</opensearch:startIndex>{}</feed>"
    ).format(total, start, "".join(entries))


def _page(start, page_size=100):
    return arxiv.search_url(CHUAN_WU.name, start, page_size)


def _html(block):
    return '<div class="ltx_authors">{}</div><div class="ltx_abstract">x</div>'.format(block)


def _sparql_rows(*signatures):
    """One DBLP paper signed by each (name, pid)."""
    rows = [
        {"title": {"value": "Joint Paper."}, "name": {"value": name},
         "creator": {"value": "https://dblp.org/pid/" + pid}}
        for name, pid in signatures
    ]
    return json.dumps({"results": {"bindings": rows}})


DBLP_URL = dblp.person_papers_query_url(CHUAN_WU.dblp_pid)
DBLP_COAUTHORS = _sparql_rows(
    ("Chuan Wu", CHUAN_WU.dblp_pid), ("Alice Smith", "1/1"), ("Bob Lee", "1/2"),
)


def _ids(entries):
    return [e.arxiv_id for e in entries]


def test_collect_keeps_entries_since_the_cutoff_and_stops_past_it():
    fetcher = StubFetcher({_page(0, 3): _feed([
        _entry("2609.00002", "2026-09-01"),
        _entry("2606.00001", SINCE),
        _entry("2605.00001", "2026-05-31"),
    ], total=50)})
    assert _ids(collect(CHUAN_WU, fetcher, SINCE, page_size=3)) == ["2609.00002", "2606.00001"]
    assert fetcher.urls == [_page(0, 3)]


def test_collect_requests_the_next_page_when_a_full_page_leaves_more():
    fetcher = StubFetcher({
        _page(0, 2): _feed([_entry("2609.00003"), _entry("2609.00002")], total=3),
        _page(2, 2): _feed([_entry("2609.00001")], total=3, start=2),
    })
    entries = collect(CHUAN_WU, fetcher, SINCE, page_size=2)
    assert _ids(entries) == ["2609.00003", "2609.00002", "2609.00001"]
    assert fetcher.urls == [_page(0, 2), _page(2, 2)]


def test_collect_continues_after_a_short_page_from_the_entries_received():
    fetcher = StubFetcher({
        _page(0, 3): _feed([_entry("2609.00005"), _entry("2609.00004")], total=5),
        _page(2, 3): _feed([_entry("2609.00003"), _entry("2609.00002"), _entry("2609.00001")],
                           total=5, start=2),
    })
    assert len(collect(CHUAN_WU, fetcher, SINCE, page_size=3)) == 5
    assert fetcher.urls == [_page(0, 3), _page(2, 3)]


def test_collect_with_no_papers_at_all_is_empty():
    assert collect(CHUAN_WU, StubFetcher({_page(0): _feed([], total=0)}), SINCE) == []


def test_collect_rejects_an_empty_page_mid_listing():
    fetcher = StubFetcher({
        _page(0, 2): _feed([_entry("2609.00003"), _entry("2609.00002")], total=5),
        _page(2, 2): _feed([], total=5, start=2),
    })
    with pytest.raises(ValueError, match="chuan-wu"):
        collect(CHUAN_WU, fetcher, SINCE, page_size=2)


def test_collect_rejects_running_out_of_pages_before_the_cutoff():
    fetcher = StubFetcher({
        _page(0, 1): _feed([_entry("2609.00003")], total=5),
        _page(1, 1): _feed([_entry("2609.00002")], total=5, start=1),
    })
    with pytest.raises(ValueError, match="chuan-wu"):
        collect(CHUAN_WU, fetcher, SINCE, page_size=1, max_pages=2)


def _one_paper(extra=None):
    mapping = {_page(0): _feed([_entry("2609.00001")], total=1)}
    mapping.update(extra or {})
    return StubFetcher(mapping)


def test_school_mode_attributes_a_paper_whose_html_names_the_school():
    fetcher = _one_paper({arxiv.html_url("2609.00001"): _html("Alice Smith Chuan Wu Bob Lee HKU")})
    assert sync_researcher(CHUAN_WU, fetcher, SINCE).papers == [{
        "arxiv_id": "2609.00001", "title": "Paper 2609.00001", "abstract": "About 2609.00001",
        "authors": AUTHORS, "published": "2026-09-01", "primary_category": "cs.DC",
        "position": 2, "attribution": "school",
    }]


def test_school_mode_without_html_falls_back_to_dblp_coauthors():
    fetcher = _one_paper({DBLP_URL: DBLP_COAUTHORS})
    synced = sync_researcher(CHUAN_WU, fetcher, SINCE)
    assert [r["attribution"] for r in synced.papers] == ["coauthor"]
    assert (synced.candidates, synced.without_html) == (1, 1)


def test_an_html_fetch_error_other_than_404_fails_the_researcher():
    fetcher = _one_paper({arxiv.html_url("2609.00001"): HttpError("server error", 500)})
    # Matched on the message: swallowing the 500 would reach the unstubbed
    # DBLP URL, whose NotFound is an HttpError too.
    with pytest.raises(HttpError, match="server error"):
        sync_researcher(CHUAN_WU, fetcher, SINCE)


def test_name_mode_never_fetches_html():
    fetcher = _one_paper()
    [record] = sync_researcher(replace(CHUAN_WU, match="name"), fetcher, SINCE).papers
    assert record["attribution"] == "name"
    assert fetcher.urls == [_page(0)]


def test_strict_mode_fetches_dblp_once_for_several_candidates():
    at_hku = _html("Alice Smith Chuan Wu Bob Lee HKU")
    fetcher = StubFetcher({
        _page(0): _feed([_entry("2609.00002"), _entry("2609.00001")], total=2),
        arxiv.html_url("2609.00002"): at_hku,
        arxiv.html_url("2609.00001"): at_hku,
        DBLP_URL: DBLP_COAUTHORS,
    })
    records = sync_researcher(replace(CHUAN_WU, match="strict"), fetcher, SINCE).papers
    assert [r["attribution"] for r in records] == ["school+coauthor"] * 2
    assert fetcher.urls.count(DBLP_URL) == 1


# --- merge_feed ------------------------------------------------------------

def _person(slug, name="Name", affiliation="Somewhere"):
    return Researcher(
        slug=slug, name=name, dblp_pid="0/0", affiliation=affiliation,
        known_for="Things", match="name",
    )


def _paper(arxiv_id, published="2026-09-01", title="T"):
    return {
        "arxiv_id": arxiv_id, "title": title, "abstract": "", "authors": ["Name"],
        "published": published, "primary_category": "cs.DC", "position": 1,
        "attribution": "name",
    }


def _feed_file(papers_by_slug):
    return {
        "schema": 1, "generated": "2026-09-14",
        "researchers": [
            {"slug": slug, "name": "Old", "affiliation": "Old", "known_for": "Old",
             "papers": papers}
            for slug, papers in papers_by_slug.items()
        ],
    }


def _papers_of(feed, slug):
    [item] = [r for r in feed["researchers"] if r["slug"] == slug]
    return item["papers"]


def test_merge_gives_a_synced_researcher_only_this_runs_papers():
    previous = _feed_file({"a": [
        _paper("2605.00001", "2026-05-01"), _paper("2609.00001", title="v1 title"),
    ]})
    fresh = {"a": [_paper("2609.00001", title="v2 title")]}
    feed = merge_feed(previous, [_person("a")], fresh, "2026-09-28")
    assert _papers_of(feed, "a") == fresh["a"]


def test_merge_keeps_the_papers_of_a_researcher_whose_sync_failed():
    previous = _feed_file({"a": [_paper("2609.00001")], "b": [_paper("2609.00002")]})
    feed = merge_feed(previous, [_person("a"), _person("b")], {"a": []}, "2026-09-28")
    assert [p["arxiv_id"] for p in _papers_of(feed, "b")] == ["2609.00002"]


def test_merge_drops_a_researcher_gone_from_the_yaml():
    previous = _feed_file({"a": [_paper("2609.00001")], "gone": [_paper("2609.00002")]})
    feed = merge_feed(previous, [_person("a")], {}, "2026-09-28")
    assert [r["slug"] for r in feed["researchers"]] == ["a"]


def test_merge_orders_researchers_as_the_yaml_and_papers_newest_first():
    fresh = {"a": [
        _paper("2608.00009", "2026-08-30"),
        _paper("2609.00001", "2026-09-02"),
        _paper("2609.00002", "2026-09-02"),
    ]}
    feed = merge_feed(None, [_person("b"), _person("a")], fresh, "2026-09-28")
    assert [r["slug"] for r in feed["researchers"]] == ["b", "a"]
    assert [p["arxiv_id"] for p in _papers_of(feed, "a")] == [
        "2609.00002", "2609.00001", "2608.00009",
    ]


def test_merge_takes_everything_but_the_papers_from_the_yaml():
    previous = _feed_file({"a": [_paper("2609.00001")]})
    feed = merge_feed(previous, [_person("a", "Ion Stoica", "UC Berkeley")], {}, "2026-09-28")
    assert feed["schema"] == 1 and feed["generated"] == "2026-09-28"
    [item] = feed["researchers"]
    assert (item["name"], item["affiliation"], item["known_for"]) == (
        "Ion Stoica", "UC Berkeley", "Things",
    )
