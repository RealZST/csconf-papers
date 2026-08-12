# csconf-papers

Accepted paper lists for top systems and database conferences, generated from DBLP.

Data lives in `data/{year}/{VENUE}.json`; human-readable listings in `papers/{year}/{VENUE}.md`.

Paper links come from DBLP where available. For editions DBLP has not indexed yet, the list is scraped from the conference site — which carries no links — and missing links are matched by title against Semantic Scholar, usually resolving to an arXiv preprint. Those are marked with their host in the listings and with `url_source` in the JSON. A paper with no link anywhere falls back to a Google Scholar search URL.

PDF links are derived from the link each paper already has: PVLDB points at a PDF directly, a USENIX presentation URL yields the file under `/system/files/` (checked with a HEAD request before it is published), and an ACM DOI builds a `dl.acm.org` address. The last kind is labelled `PDF (ACM)` because it needs a subscription unless the paper is open access.

Last updated: 2026-08-12

| Year | SOSP | OSDI | ATC | NSDI | EuroSys | ASPLOS | SIGMOD | VLDB |
|---|---|---|---|---|---|---|---|---|
| 2025 | [66](papers/2025/SOSP.md) | [53](papers/2025/OSDI.md) | [100](papers/2025/ATC.md) | [83](papers/2025/NSDI.md) | [85](papers/2025/EuroSys.md) | [179](papers/2025/ASPLOS.md) | — | [483](papers/2025/VLDB.md) |
| 2026 | [105](papers/2026/SOSP.md) | [136](papers/2026/OSDI.md) | — | [150](papers/2026/NSDI.md) | [138](papers/2026/EuroSys.md) | [155](papers/2026/ASPLOS.md) | [354](papers/2026/SIGMOD.md) | [135](papers/2026/VLDB.md) |

