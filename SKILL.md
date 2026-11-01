---
name: insee-mcp-tools
description: "Use when the user needs French statistics from the combined INSEE, MELODI, and RMES MCP server: publications, datasets, observations, or metadata."
version: 1.0.0
license: Apache-2.0
metadata:
  hermes:
    tags: [mcp, statistics, france, insee, publications]
---

# INSEE MCP — combined tool guide

Use this guide when connected to the aggregate MCP server. It combines the insee.fr, MELODI, and RMES tool families in one server. Choose the family by the kind of answer needed; each workflow below is self-contained.

## Tool inventory

The aggregate currently exposes exactly these 11 tools:

**insee.fr — publications, rapid releases, and curated key indicators**
- `search_insee_documents`
- `get_insee_homepage`
- `get_insee_document`
- `search_insee_conjoncture`
- `search_insee_chiffrecle`

**MELODI — dataset catalogue and observations**
- `search_melodi_datasets`
- `search_melodi_modalities`
- `get_melodi_observations`

**RMES — RDF metadata and SPARQL**
- `search_rmes_graphs`
- `describe_rmes_resource`
- `run_rmes_sparql`

## Select a workflow

### insee.fr

- For a generic national indicator, start with `get_insee_homepage`. It returns curated French indicator sentences with their periods. These entries are bundled literals, not refreshed at call time; quote the returned period and do not call them live.
- For a simple factual statistic or synthetic key-figure table, use `search_insee_chiffrecle`.
- For the latest monthly, quarterly, or annual *Informations rapides* release, use `search_insee_conjoncture` with several French keywords or synonyms. Leave the year filter unset when looking for the latest match.
- For detailed analysis, history, methodology, or regional profiles, use `search_insee_documents` with a rich French query.
- To fetch full text, pass a relative URL returned by `search_insee_documents`, `search_insee_conjoncture`, or `search_insee_chiffrecle` to `get_insee_document`. Never guess a document URL or publication id. Content is truncated by default; set `truncate_content` to false only when needed.

### MELODI

For filtered observations, use the three-stage discovery chain:

1. `search_melodi_datasets` with an explicit French description; take the exact dataset id and column ids from its results.
2. `search_melodi_modalities` with that dataset id, the relevant column ids, and a French description of the desired values; take the exact modality codes from its results.
3. `get_melodi_observations` with the discovered dataset id and column filters built from the exact column ids and modality codes. Use `years` to restrict time periods; an empty list means all available years. The default limit is 100 observations.

If no column filter is needed, `column_filters` may be empty. Never guess dataset ids, column ids, or modality codes.

### RMES

1. Start with `search_rmes_graphs` to discover named graphs. Its default response is a condensed category summary with counts and examples; narrow by category or URI substring to receive the full listing for the selected results.
2. Query discovered graph URIs with `run_rmes_sparql`. Scope the query to named graphs, add a `LIMIT`, and filter French SKOS labels with `lang(?label) = "fr"`. The tool adds a row limit if the query has none and reports it in the result. SELECT/ASK-style results are JSON; CONSTRUCT/DESCRIBE results are Turtle.
3. For every property of a known RDF resource, use `describe_rmes_resource` with the exact resource URI from graph results or SPARQL bindings; pass a discovered graph URI to narrow the search when possible.

Never guess graph or resource URIs. RMES returns metadata and classifications, not statistical figures.

## Shared rules

- INSEE search data is French: use French keywords and useful synonyms. Publication content and the bundled indicator sentences are in French.
- Treat every dataset id, column id, modality code, document URL, graph URI, and resource URI as opaque. Obtain each from the preceding discovery result and preserve it exactly.
- An empty result is valid. Broaden the query or relax filters before treating it as a failure.
- Report periods, units, and geographic scope as returned. Do not infer a more current period than the result provides.
