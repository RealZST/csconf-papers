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
        {"name": "Patrick H. Coppock", "pid": "405/6876", "orcid": "0000-0002-7101-6961"}
    ]
    assert data["source"] == "dblp"
    # 会议类记录这些字段必须存在且为 None，下游依赖字段齐整
    for absent in ("published_month", "volume", "issue"):
        assert absent in data and data[absent] is None


def test_paper_merge_key_normalizes_title():
    a = Paper(title="LithOS: An OS for ML on GPUs.", authors=[], venue="SOSP", year=2025)
    b = Paper(title="lithos  an os for ml on gpus", authors=[], venue="SOSP", year=2025)
    assert a.merge_key() == b.merge_key()
