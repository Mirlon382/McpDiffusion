---
name: insee-fr-tools
description: "Use when the user asks for INSEE publications, rapid releases, or curated national indicators available from insee.fr."
version: 1.0.0
license: Apache-2.0
metadata:
  hermes:
    tags: [mcp, statistics, france, insee, publications]
---

# INSEE MCP — insee.fr tools

Use this guide when connected to the standalone insee.fr MCP server. It covers five tools for INSEE publications, *Informations rapides*, Chiffres-cles search results, and the server's curated national indicators. It does not cover other data services.

## Choose the right tool

1. For a general national indicator question, start with `get_insee_homepage`. It returns the server's curated indicator entries as French sentences, each stating its figure and period. These entries are bundled literals and are not refreshed by the call: quote the period as returned and do not describe the figures as live.
2. For a simple factual statistic or a synthetic key-figure table, use `search_insee_chiffrecle`. It accepts a natural-language query and optional year and geography filters.
3. For the latest monthly, quarterly, or annual rapid release (*Informations rapides*), use `search_insee_conjoncture`. Give it several related French keywords or synonyms. For a latest-release question, leave the year filter unset so the freshest match can rank first.
4. For detailed analysis, history, methodology, thematic reports, or regional profiles, use `search_insee_documents`. Use a rich French query with relevant context, synonyms, year, and geography.
5. To read a publication, pass a relative document URL returned by one of the three search tools above to `get_insee_document`. Never invent or reconstruct a URL or publication id. The tool accepts up to ten URLs per call. Content is truncated by default; set `truncate_content` to false only when the full text is needed.

## Search and identifier rules

- Search with French terms and useful synonyms; results and extracted publication content are in French.
- Treat document URLs and publication ids as opaque. Discover them with `search_insee_documents`, `search_insee_conjoncture`, or `search_insee_chiffrecle` before fetching.
- An empty search result is valid. Broaden the query or relax filters rather than treating it as a service failure.
- `get_insee_homepage` has no input parameters and returns national indicators, not geographic breakdowns or a publication catalogue.
- The search tools return structured publication records. Use the result's `url` value as the input for `get_insee_document`.
