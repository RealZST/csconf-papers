from csconf.models import Author, Paper


def test_paper_serializes_with_all_schema_fields():
    paper = Paper(
        title="LithOS: An Operating System for Efficient Machine Learning on GPUs",
        authors=[Author(name="Patrick H. Coppock", pid="405/6876", orcid="0000-0002-7101-6961")],
        venue="SOSP",
        year=2025,
        published_year=2025,
        doi="10.1145/3731569.3764818",
        url="https://doi.org/10.1145/3731569.3764818",
        pages="1-17",
        dblp_paper_key="conf/sosp/CoppockZSKYSSM025",
    )
    data = paper.to_dict()

    assert data["title"].endswith("on GPUs")
    assert data["authors"] == [
        {
            "name": "Patrick H. Coppock",
            "display_name": "Patrick H. Coppock",
            "pid": "405/6876",
            "orcid": "0000-0002-7101-6961",
        }
    ]
    assert data["source"] == "dblp"
    # These must be present and None for conference records; downstream code
    # relies on a uniform shape
    for absent in ("published_month", "volume", "issue"):
        assert absent in data and data[absent] is None


def test_paper_merge_key_normalizes_title():
    a = Paper(title="LithOS: An OS for ML on GPUs.", authors=[], venue="SOSP", year=2025)
    b = Paper(title="lithos  an os for ml on gpus", authors=[], venue="SOSP", year=2025)
    assert a.merge_key() == b.merge_key()


def test_author_carries_a_display_name_with_the_dblp_suffix_stripped():
    """DBLP appends a four-digit suffix to tell apart different people who share
    a name: "Li Jiang 0002" is the second Li Jiang, and its pid is 45/4954-2.
    The canonical form has to stay — stripping it before matching would merge
    two real people — but no reader should see it, and every consumer of this
    data should not have to know that rule. So both forms ship."""
    from csconf.models import Author

    author = Author(name="Li Jiang 0002", pid="45/4954-2")

    assert author.to_dict() == {
        "name": "Li Jiang 0002",
        "display_name": "Li Jiang",
        "pid": "45/4954-2",
        "orcid": None,
    }


def test_display_name_equals_name_when_there_is_no_suffix():
    from csconf.models import Author

    assert Author(name="Zhuoran Song").to_dict()["display_name"] == "Zhuoran Song"


def test_display_name_is_derived_not_stored():
    """It round-trips from the canonical name, so a stale value in an old file
    can never disagree with it."""
    from csconf.models import Author

    restored = Author.from_dict(
        {"name": "Li Jiang 0002", "display_name": "whatever was there", "pid": "1/2"}
    )

    assert restored.to_dict()["display_name"] == "Li Jiang"


def test_only_a_trailing_four_digit_group_is_a_suffix():
    from csconf.models import display_name

    assert display_name("Chenhao Ma 0001") == "Chenhao Ma"
    assert display_name("Deep Learning 2020 Team") == "Deep Learning 2020 Team"
    assert display_name("Jianliang Xu") == "Jianliang Xu"
