from __future__ import annotations

from typing import List, Sequence

from csconf.models import Paper


def filter_by_rounds(
    papers: Sequence[Paper], rounds: Sequence[Sequence[int]]
) -> List[Paper]:
    """保留属于该届会议的 (卷, 期)。

    rounds 是 [[卷, 期], ...]，来自官方会议站点——一届 SIGMOD 横跨两卷四期。
    匹配用论文自身的 volume/issue 字段而非调用方声明的卷号：否则把 vol 3 的
    论文误标成 vol 4 时，会把 vol 3 里同期号的论文当成 vol 4 的收进来。
    这也让本函数可以一次接收多卷的论文。

    PODS 的期不出现在 SIGMOD 的 rounds 中，因此无需任何 track 判别逻辑。
    rounds 来自 YAML 是整数，Paper.volume/issue 解析自 XML 是字符串，
    两侧统一转成字符串再比——弄错的话会静默返回空列表。
    """
    wanted = {(str(vol), str(issue)) for vol, issue in rounds}
    return [p for p in papers if (p.volume, p.issue) in wanted]
