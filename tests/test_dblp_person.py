import json
from pathlib import Path

import pytest

from csconf import dblp

FIXTURES = Path(__file__).parent / "fixtures"
PID = "68/3340-8"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _row(title, name, creator):
    return {"title": {"value": title}, "name": {"value": name}, "creator": {"value": creator}}


def _profile_from(*rows):
    return dblp.parse_person_profile(json.dumps({"results": {"bindings": list(rows)}}), PID)


def test_person_query_targets_the_pid():
    url = dblp.person_papers_query_url(PID)
    assert url.startswith(dblp.SPARQL_ENDPOINT)
    assert "68%2F3340-8" in url


def test_profile_reads_arxiv_ids_in_both_corr_link_shapes():
    """Records up to 2021 link arxiv.org/abs; later ones carry only the
    10.48550 DOI. Every other DOI in the fixture must be ignored."""
    profile = dblp.parse_person_profile(_read("sparql-person.json"), PID)
    assert profile.arxiv_ids == {
        "1802.08236", "1902.05260", "1904.08964", "2009.13003",
        "2302.11665", "2607.01633", "2607.05543", "2607.18002",
    }


def test_profile_counts_joint_papers_by_title():
    profile = dblp.parse_person_profile(_read("sparql-person.json"), PID)
    assert profile.coauthors["xuanzheliu"] == 16
    # 10 records, one of them the CoRR twin of another
    assert profile.coauthors["yinminzhong"] == 9


def test_profile_leaves_out_the_person_and_homonyms():
    profile = dblp.parse_person_profile(_read("sparql-person.json"), PID)
    assert "xinjin" not in profile.coauthors
    assert "hongxu" not in profile.coauthors       # "Hong Xu 0001"
    assert "haoyuzhang" not in profile.coauthors   # unsuffixed, pid 168/0332 is a disambiguation page


def test_one_homonym_signature_leaves_a_name_out_whatever_the_order():
    profile = _profile_from(
        _row("A.", "Wei Wang 0030", "https://dblp.org/pid/2/2"),
        _row("A.", "Wei Wang", "https://dblp.org/pid/2/1"),
        _row("A.", "Yuliang Liu", "https://dblp.org/pid/1/1"),
        _row("B.", "Bo Li", "https://dblp.org/pid/3/1"),
        _row("C.", "Bo Li 0061", "https://dblp.org/pid/3/2"),
    )
    assert profile.coauthors == {"yuliangliu": 1}


def test_names_without_latin_letters_are_not_counted():
    profile = _profile_from(
        _row("A.", "王伟", "https://dblp.org/pid/4/1"),
        _row("B.", "李娜", "https://dblp.org/pid/4/2"),
    )
    assert profile.coauthors == {}


def test_pid_without_records_is_an_error():
    with pytest.raises(dblp.BadResponse, match=PID):
        _profile_from()


def test_norm_name_ignores_punctuation_suffix_and_accents():
    assert dblp.norm_name("Yu-Liang Liu") == dblp.norm_name("Yuliang Liu") == "yuliangliu"
    assert dblp.norm_name("Xin Jin 0008") == "xinjin"
    assert dblp.norm_name("Robert Soulé") == dblp.norm_name("Robert Soule")
