from __future__ import annotations

import pytest

from csconf.arxiv import ArxivEntry
from csconf.attribution import author_position, decide, is_candidate
from csconf.dblp import PersonProfile
from csconf.models import Researcher


def _entry(authors, category="cs.DC"):
    return ArxivEntry(
        arxiv_id="2609.00001", title="T", abstract="", authors=authors,
        published="2026-09-01", primary_category=category,
    )


def _researcher(match):
    return Researcher(
        slug="chuan-wu", name="Chuan Wu", dblp_pid="34/3772-1", affiliation="HKU",
        known_for="", match=match, schools=["\\bHKU\\b"],
    )


def _profile(coauthors=None, arxiv_ids=()):
    return PersonProfile(arxiv_ids=set(arxiv_ids), coauthors=dict(coauthors or {}))


PAPER = _entry(["Alice Smith", "Chuan Wu", "Bob Lee"])
AT_SCHOOL = "Alice Smith Chuan Wu Bob Lee HKU"
ELSEWHERE = "Alice Smith Chuan Wu Bob Lee Tsinghua University"
# Profile keys are normalized names, as parse_person_profile writes them.
BOTH_COAUTHORS = _profile({"alicesmith": 1, "boblee": 1})


def test_position_is_one_based():
    assert author_position(_entry(["Alice Smith", "Chuan Wu"]), "Chuan Wu") == 2


def test_position_ignores_spacing_and_accents():
    assert author_position(_entry(["Chuan  Wü"]), "Chuan Wu") == 1


def test_position_is_none_when_absent():
    assert author_position(_entry(["Alice Smith"]), "Chuan Wu") is None


def test_non_cs_primary_is_not_a_candidate():
    assert not is_candidate(_entry(["Chuan Wu"], category="physics.optics"), _researcher("name"))


def test_thirty_authors_is_a_candidate_but_thirty_one_is_not():
    thirty = ["Chuan Wu"] + ["Someone Else"] * 29
    assert is_candidate(_entry(thirty), _researcher("name"))
    assert not is_candidate(_entry(thirty + ["One More"]), _researcher("name"))


def test_paper_without_the_person_is_not_a_candidate():
    assert not is_candidate(_entry(["Alice Smith"]), _researcher("name"))


def test_name_mode_accepts_any_candidate():
    assert decide(PAPER, _researcher("name"), ELSEWHERE, _profile()) == "name"


def test_school_mode_accepts_a_block_naming_the_school():
    assert decide(PAPER, _researcher("school"), AT_SCHOOL, _profile()) == "school"


def test_school_mode_rejects_a_block_without_the_school_even_with_coauthors():
    assert decide(PAPER, _researcher("school"), ELSEWHERE, BOTH_COAUTHORS) is None


@pytest.mark.parametrize("match", ["school", "strict"])
def test_without_a_block_two_known_coauthors_link_the_paper(match):
    assert decide(PAPER, _researcher(match), None, BOTH_COAUTHORS) == "coauthor"


def test_without_a_block_one_coauthor_with_one_joint_paper_is_not_enough():
    assert decide(PAPER, _researcher("school"), None, _profile({"alicesmith": 1})) is None


def test_without_a_block_one_coauthor_with_two_joint_papers_links_the_paper():
    assert decide(PAPER, _researcher("school"), None, _profile({"alicesmith": 2})) == "coauthor"


def test_the_person_is_not_counted_as_their_own_coauthor():
    profile = _profile({"chuanwu": 5})
    assert decide(_entry(["Chuan Wu"]), _researcher("school"), None, profile) is None


def test_without_a_block_an_arxiv_id_dblp_lists_links_the_paper():
    profile = _profile(arxiv_ids={PAPER.arxiv_id})
    assert decide(PAPER, _researcher("school"), None, profile) == "coauthor"


def test_strict_mode_accepts_school_and_coauthors():
    assert decide(PAPER, _researcher("strict"), AT_SCHOOL, BOTH_COAUTHORS) == "school+coauthor"


def test_strict_mode_rejects_the_school_without_coauthors():
    assert decide(PAPER, _researcher("strict"), AT_SCHOOL, _profile()) is None


def test_strict_mode_rejects_coauthors_at_another_school():
    assert decide(PAPER, _researcher("strict"), ELSEWHERE, BOTH_COAUTHORS) is None
