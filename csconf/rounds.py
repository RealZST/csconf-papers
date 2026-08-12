from __future__ import annotations

from typing import List, Sequence

from csconf.models import Paper


def filter_by_rounds(
    papers: Sequence[Paper], rounds: Sequence[Sequence[int]]
) -> List[Paper]:
    """Keep the (volume, issue) pairs that belong to this edition.

    rounds is [[volume, issue], ...] taken from the official conference site —
    one SIGMOD edition spans two volumes and four issues. Matching uses the
    volume/issue on the papers themselves rather than a volume the caller
    declares: mislabelling volume 3 papers as volume 4 would otherwise pull in
    every volume 3 paper that happens to share an issue number. It also lets
    this function take papers from several volumes at once.

    PODS issues never appear in SIGMOD's rounds, so no track logic is needed.
    rounds comes from YAML as integers while Paper.volume/issue is parsed from
    XML as strings; both sides are stringified before comparing, because
    getting that wrong returns an empty list without a word.
    """
    wanted = {(str(vol), str(issue)) for vol, issue in rounds}
    return [p for p in papers if (p.volume, p.issue) in wanted]
