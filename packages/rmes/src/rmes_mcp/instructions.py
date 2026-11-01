"""The handshake text this brick sends. It describes RMES and nothing else."""

from textwrap import dedent

# Sent to the client in the handshake. Only what belongs to no single tool: which tool to call, and
# when, is in the tool descriptions, where it reaches the model even when a client drops these
# instructions.

# language=Markdown
INSTRUCTIONS = dedent("""
    This server exposes RMES, the INSEE repository of statistical metadata, queried over SPARQL at
    rdf.insee.fr. It holds definitions, nomenclatures and classifications -- no figures.

    Start with `search_rmes_graphs`: it lists the available named graphs by category, and there are
    more than 700 of them. Write SPARQL against the graphs it names.

    Rules that apply to every tool:

    - Never guess a graph URI or a resource URI. Each is opaque and must come from `search_rmes_graphs`
      first.
    - An empty result is a valid answer, not a failure. It usually means the query was too narrow.
    - This server answers with metadata only. It has no statistical figures to return.
""").strip()
