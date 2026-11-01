---
name: rmes-tools
description: "Use when the user needs INSEE statistical metadata, definitions, vocabularies, or classifications from RMES."
version: 1.0.0
license: Apache-2.0
metadata:
  hermes:
    tags: [mcp, statistics, france, rmes, sparql, metadata]
---

# RMES MCP — RDF metadata and SPARQL tools

Use this guide when connected to the standalone RMES MCP server. RMES contains INSEE statistical metadata, definitions, vocabularies, and classifications; it does not contain statistical observations or figures.

## Discovery-to-query workflow

1. Start with `search_rmes_graphs` to discover named graphs. With the default `graph_category=ALL`, the response is a condensed summary by category with counts and example graph URIs, not a flat list. Narrow with `graph_category` or `graph_uri_substring` to get the full graph listing for the selected results; `expand_graphs=true` also requests it.
2. Use the exact graph URI returned by discovery in a `run_rmes_sparql` query. Scope queries to one or more named graphs instead of scanning the whole store. Add an explicit `LIMIT`; if none is present, the server adds a row limit and reports that in the result. For French SKOS labels, filter the language to `fr` to avoid multilingual duplicates.
3. If you need all known properties of one RDF resource, pass its exact discovered `resource_uri` to `describe_rmes_resource`. Its optional `graph_uri` narrows the lookup; without it, the search spans all graphs and is slower.

## Rules for identifiers and results

- Never guess a graph URI or resource URI. Discover graph URIs with `search_rmes_graphs`; obtain resource URIs from graph results or SPARQL bindings.
- Treat URIs as opaque and copy them exactly into the query or tool argument.
- `run_rmes_sparql` accepts SELECT, ASK, CONSTRUCT, and DESCRIBE queries. SELECT/ASK-style results are returned as JSON bindings; CONSTRUCT/DESCRIBE results are returned as Turtle.
- Query timeouts are capped at 60 seconds. The default maximum row count is 200, and the server caps it at 2,000.
- Empty results are valid and often mean the graph or query constraints are too narrow. RMES provides metadata only, not figures.
