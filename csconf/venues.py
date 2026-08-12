from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import yaml


@dataclass(frozen=True)
class Fetch:
    """One TOC fetch to perform. volume is set for journals only, for filtering."""

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
            "volumes: auto needs a volume_lookup callback to discover which "
            "volumes exist for that year"
        )
    volumes = volume_lookup(config["index"], year)
    return [Fetch(toc_key=template.format(year=year, vol=v), volume=v) for v in volumes]


def _journal_volume_fetches(config: Dict[str, Any], year: int) -> List[Fetch]:
    volume = config["vol_for_year"][year]
    return [Fetch(toc_key=config["key"].format(vol=volume), volume=volume)]


def _journal_rounds_fetches(config: Dict[str, Any], year: int) -> List[Fetch]:
    """One edition spans several volumes and issues; fetch each volume once,
    keeping the order in which it first appears in the config."""
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
    raise ValueError("unknown venue type: {}".format(kind))


def discover_volumes(index_html: str, slug: str, year: int) -> List[int]:
    """Discover which volumes exist for a year from the DBLP venue index page.

    Returned in ascending order. ASPLOS changes volume count from year to year
    (four in 2024, three in 2025, two in 2026), so it cannot be hardcoded.
    """
    pattern = re.compile(r"\b{}{}-(\d+)\b".format(re.escape(slug), year))
    volumes = {int(match) for match in pattern.findall(index_html)}
    return sorted(volumes)
