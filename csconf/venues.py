from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import yaml


@dataclass(frozen=True)
class Fetch:
    """一次待执行的 TOC 抓取。volume 仅期刊类有值，用于后续按卷过滤。"""

    toc_key: str
    volume: Optional[int]


def load_venues(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def status_of(venues: Dict[str, Any], venue: str, year: int) -> Optional[str]:
    return venues[venue].get("status", {}).get(year)


def _conf_fetches(
    config: Dict[str, Any],
    year: int,
    volume_lookup: Optional[Callable[[str, int], List[int]]],
) -> List[Fetch]:
    template = config["key"]
    if config.get("volumes") != "auto":
        return [Fetch(toc_key=template.format(year=year), volume=None)]

    if volume_lookup is None:
        raise ValueError(
            "volumes: auto 需要 volume_lookup 回调来发现该年实际存在的卷号"
        )
    volumes = volume_lookup(config["index"], year)
    return [Fetch(toc_key=template.format(year=year, vol=v), volume=v) for v in volumes]


def _journal_volume_fetches(config: Dict[str, Any], year: int) -> List[Fetch]:
    volume = config["vol_for_year"][year]
    return [Fetch(toc_key=config["key"].format(vol=volume), volume=volume)]


def _journal_rounds_fetches(config: Dict[str, Any], year: int) -> List[Fetch]:
    """一届会议横跨多卷多期；按卷去重后抓取，保持配置中首次出现的顺序。"""
    ordered_volumes: List[int] = []
    for volume, _issue in config["rounds"][year]:
        if volume not in ordered_volumes:
            ordered_volumes.append(volume)
    return [Fetch(toc_key=config["key"].format(vol=v), volume=v) for v in ordered_volumes]


def expand(
    venues: Dict[str, Any],
    venue: str,
    year: int,
    volume_lookup: Optional[Callable[[str, int], List[int]]],
) -> List[Fetch]:
    config = venues[venue]
    kind = config["type"]

    if kind == "conf":
        return _conf_fetches(config, year, volume_lookup)
    if kind == "journal_volume":
        return _journal_volume_fetches(config, year)
    if kind == "journal_rounds":
        return _journal_rounds_fetches(config, year)
    raise ValueError("未知的 venue type: {}".format(kind))


def discover_volumes(index_html: str, slug: str, year: int) -> List[int]:
    """从 DBLP venue 索引页发现某年实际存在的卷号，升序返回。

    ASPLOS 的卷数逐年变化（实测 2024 四卷、2025 三卷、2026 两卷），
    因此不能在配置里写死。
    """
    pattern = re.compile(r"\b{}{}-(\d+)\b".format(re.escape(slug), year))
    volumes = {int(match) for match in pattern.findall(index_html)}
    return sorted(volumes)
