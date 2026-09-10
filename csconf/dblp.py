from __future__ import annotations

import json
import re
import sys
import urllib.parse
from typing import Any, Dict, List, Optional

from csconf.models import Author, Paper

# In September 2026 dblp.org put its whole website — TOC XML exports, search
# API, and both mirrors included — behind Anubis proof-of-work bot protection,
# and its robots.txt now disallows everything. The SPARQL endpoint is the
# programmatic access dblp still offers, and dblp:listedOnTocPage carries the
# very same TOC keys venues.yaml already uses, so only this fetch layer had to
# move.
SPARQL_ENDPOINT = "https://sparql.dblp.org/sparql"

_REC_PREFIX = "https://dblp.org/rec/"
_PID_PREFIX = "https://dblp.org/pid/"
_ORCID_PREFIX = "https://orcid.org/"

DOI_PREFIX = "https://doi.org/"

# DBLP occasionally drops the slash out of an ACM DOI: SIGMOD 2026's "Task
# Cascades for Efficient Unstructured Data Processing" is recorded as
# "10.11453786702" (confirmed against dblp.org's own API, so it is upstream and
# not a parsing slip here). Crossref registers that paper under 10.1145/3786702
# with a matching title and volume/issue, so splicing the slash back in recovers
# the real DOI instead of inventing one. Every ACM DOI has the shape
# 10.1145/<digits>, which makes the repair deterministic — but only for that
# prefix. Other publishers number differently, and doing this to an IEEE or
# Springer DOI would turn a broken link into a confidently wrong one.
_ACM_DOI_MISSING_SLASH = re.compile(r"^10\.1145(\d+)$")

# Non-paper records that journal volumes carry
_FRONT_MATTER = re.compile(r"^front matter\.?$", re.IGNORECASE)
# PACMMOD editorial titles come in three observed shapes: with a colon, with a
# comma after PACMMOD, and without a colon. The pattern has to tolerate all
# three — missing the second one previously led to the wrong conclusion that an
# issue had no editorial at all.
_PACMMOD_EDITORIAL = re.compile(r"PACMMOD,?\s*V\d+,\s*N\d+\s*\((?:SIGMOD|PODS)\)", re.IGNORECASE)

# Some proceedings carry their demo or poster track in the same volume. MobiCom
# 2025 is 157 DBLP entries of which 80 are titled "Demo: ...", and those are not
# accepted papers. The publisher labels them itself, so the prefix is a reliable
# signal rather than a guess — unlike length, which would be wrong: SIGCOMM 2025
# has a Short Papers section whose 14 three-page entries are peer-reviewed
# papers sitting under that heading in DBLP's own TOC. The colon is required, so
# "Demonstrating ..." and "Posterior ..." are untouched.
_TRACK_LABEL = re.compile(r"^(?:demo|poster|abstract)\s*:", re.IGNORECASE)

# dblp:monthOfPublication is an xsd:gMonth ("--09"), while the XML exports this
# code used to read carried month names, which is also what data files on disk
# already hold. Keep publishing names so the stored format does not change.
_MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
    7: "July", 8: "August", 9: "September", 10: "October", 11: "November",
    12: "December",
}

# One row per (paper, author signature); scalar fields repeat on every row of a
# paper and get read off its first. Proceedings front-matter records are typed
# neither Inproceedings nor Article, so the VALUES clause drops them at the
# server — the old XML parser did the same by tag name. ORDER BY makes both the
# paper order and the within-paper author order deterministic.
_TOC_QUERY = """\
PREFIX dblp: <https://dblp.org/rdf/schema#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?paper ?title ?year ?month ?volume ?issue ?pages ?primary ?ord ?name ?pid ?orcid WHERE {{
  ?paper dblp:listedOnTocPage <https://dblp.org/db/{toc_key}> .
  ?paper rdf:type ?type . VALUES ?type {{ dblp:Inproceedings dblp:Article }}
  ?paper dblp:title ?title .
  OPTIONAL {{ ?paper dblp:yearOfPublication ?year }}
  OPTIONAL {{ ?paper dblp:monthOfPublication ?month }}
  OPTIONAL {{ ?paper dblp:publishedInJournalVolume ?volume }}
  OPTIONAL {{ ?paper dblp:publishedInJournalVolumeIssue ?issue }}
  OPTIONAL {{ ?paper dblp:pagination ?pages }}
  OPTIONAL {{ ?paper dblp:primaryDocumentPage ?primary }}
  OPTIONAL {{ ?paper dblp:hasSignature ?sig .
             ?sig dblp:signatureDblpName ?name ; dblp:signatureOrdinal ?ord .
             OPTIONAL {{ ?sig dblp:signatureCreator ?pid }}
             OPTIONAL {{ ?sig dblp:signatureOrcid ?orcid }} }}
}} ORDER BY ?paper xsd:integer(?ord)"""

# Which TOC pages a venue's stream has papers on — this is how the volume count
# for a year is discovered (ASPLOS has four 2024 TOCs, three for 2025, two for
# 2026 so far). The old code read the venue index HTML page for the same fact.
_STREAM_TOCS_QUERY = """\
PREFIX dblp: <https://dblp.org/rdf/schema#>
SELECT DISTINCT ?toc WHERE {{
  ?paper dblp:publishedInStream <https://dblp.org/streams/{index_key}> ;
         dblp:listedOnTocPage ?toc .
}} ORDER BY ?toc"""


class BadResponse(Exception):
    """The endpoint answered 200 with something that is not a SPARQL result.

    Worth its own name because of how dblp's bot protection failed: the
    challenge page came back as HTTP 200 text/html, so the status-code checks
    all passed and the only symptom was a JSON parse error with no hint of the
    real cause.
    """


def toc_query_url(toc_key: str) -> str:
    return _query_url(_TOC_QUERY.format(toc_key=toc_key))


def stream_tocs_query_url(index_key: str) -> str:
    return _query_url(_STREAM_TOCS_QUERY.format(index_key=index_key))


def _query_url(query: str) -> str:
    return SPARQL_ENDPOINT + "?" + urllib.parse.urlencode({"query": query})


def _bindings(json_text: str) -> List[Dict[str, Any]]:
    try:
        document = json.loads(json_text)
        return document["results"]["bindings"]
    except (ValueError, KeyError, TypeError) as exc:
        raise BadResponse(
            "not a SPARQL JSON result ({}); if the body is HTML, the endpoint "
            "may be behind a bot challenge now, like dblp.org itself since "
            "2026-09".format(exc)
        ) from exc


def _value(row: Dict[str, Any], name: str) -> Optional[str]:
    entry = row.get(name)
    return entry["value"] if entry else None


def _strip_prefix(value: Optional[str], prefix: str) -> Optional[str]:
    if value and value.startswith(prefix):
        return value[len(prefix):]
    return value


def repair_doi(doi):
    """Put the slash back into an ACM DOI that DBLP recorded without one."""
    if not doi:
        return doi
    match = _ACM_DOI_MISSING_SLASH.match(doi)
    return "10.1145/{}".format(match.group(1)) if match else doi


def _clean_title(raw: Optional[str]) -> str:
    """DBLP titles all end in a period; drop it to match conference-site titles."""
    if not raw:
        return ""
    return raw.strip().rstrip(".").strip()


def is_non_paper(title: Optional[str]) -> bool:
    if not title:
        return True
    stripped = title.strip()
    return bool(
        _FRONT_MATTER.match(stripped)
        or _PACMMOD_EDITORIAL.search(stripped)
        or _TRACK_LABEL.match(stripped)
    )


def _parse_int(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _month_name(value: Optional[str]) -> Optional[str]:
    """Turn an xsd:gMonth ("--09") into the name the data files already use."""
    if value is None:
        return None
    name = _MONTH_NAMES.get(_parse_int(value.lstrip("-")))
    return name if name is not None else value


def parse_toc(json_text: str, venue: str, year: int) -> List[Paper]:
    """Parse one TOC's SPARQL result into a list of papers.

    Journal front matter and editorials are removed by is_non_paper; the demo
    and poster tracks some proceedings carry go with them.
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    order: List[str] = []
    for row in _bindings(json_text):
        record = _value(row, "paper")
        if record not in grouped:
            grouped[record] = []
            order.append(record)
        grouped[record].append(row)

    papers: List[Paper] = []
    for record in order:
        rows = grouped[record]
        first = rows[0]

        title = _clean_title(_value(first, "title"))
        if is_non_paper(title):
            continue

        authors: List[Author] = []
        seen_ordinals = set()
        for row in rows:
            name, ordinal = _value(row, "name"), _value(row, "ord")
            # A paper with several primary pages repeats each signature row;
            # the ordinal tells a genuine next author from such a duplicate.
            if name is None or ordinal in seen_ordinals:
                continue
            seen_ordinals.add(ordinal)
            authors.append(
                Author(
                    name=name.strip(),
                    pid=_strip_prefix(_value(row, "pid"), _PID_PREFIX),
                    orcid=_strip_prefix(_value(row, "orcid"), _ORCID_PREFIX),
                )
            )

        url = _value(first, "primary")
        doi = url[len(DOI_PREFIX):] if url and url.startswith(DOI_PREFIX) else None
        repaired = repair_doi(doi)
        if repaired != doi:
            # The url has to move with it. Leaving it alone would publish a
            # dead doi.org link right next to a correct DOI field.
            print("  repaired DOI {} -> {}".format(doi, repaired), file=sys.stderr)
            doi, url = repaired, DOI_PREFIX + repaired

        papers.append(
            Paper(
                title=title,
                authors=authors,
                venue=venue,
                year=year,
                published_year=_parse_int(_value(first, "year")),
                published_month=_month_name(_value(first, "month")),
                volume=_value(first, "volume"),
                issue=_value(first, "issue"),
                doi=doi,
                url=url,
                pages=_value(first, "pages"),
                source="dblp",
                dblp_paper_key=_strip_prefix(record, _REC_PREFIX),
            )
        )

    return papers


def parse_stream_tocs(json_text: str) -> List[str]:
    """The TOC page IRIs of a stream, for volume discovery."""
    return [_value(row, "toc") for row in _bindings(json_text)]
