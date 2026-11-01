---
name: melodi-tools
description: "Use when the user needs statistical datasets or observations from MELODI."
version: 1.0.0
license: Apache-2.0
metadata:
  hermes:
    tags: [mcp, statistics, france, melodi, datasets]
---

# MELODI MCP — dataset and observation tools

Use this guide when connected to the standalone MELODI MCP server. MELODI provides a searchable catalogue of statistical datasets and access to their observations.

## Discovery-to-observation workflow

For a filtered statistical query, chain these tools in order:

1. `search_melodi_datasets` — search using an explicit French description of the phenomenon, population, product, and geographic level where relevant. Do not supply codes in the query. Read the result's exact `dataset_id` and available column ids.
2. `search_melodi_modalities` — provide that exact `dataset_id`, the relevant column ids from the dataset result, and a French natural-language description of the requested values. Read the exact modality `code` returned for each column.
3. `get_melodi_observations` — use the discovered `dataset_id`; construct `column_filters` with the exact column ids and modality codes. The `years` list can restrict the returned observations by year; an empty list leaves all available years. The default response limit is 100 observations.

If all rows are wanted and no column filter is needed, `column_filters` may be empty; otherwise discover the exact modality codes before filtering.

## Rules for identifiers and search

- Never guess a dataset id, column id, or modality code. They are opaque values; obtain them from the preceding discovery result and preserve them exactly.
- Dataset and modality matching is lexical. Use French phrases with relevant synonyms rather than guessed codes.
- Dataset search defaults to the broad year interval 1900–2100 and returns up to five ranked datasets. Tighten the year bounds or result count only when useful.
- An empty result is valid. Re-check the dataset and modality values and broaden the French query before concluding that data is unavailable.
- Observations include dimensions, attributes, and a measure. Preserve the returned unit and time period when presenting a value.
