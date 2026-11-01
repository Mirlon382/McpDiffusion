"""The handshake text this brick sends. It describes insee.fr and nothing else."""

from textwrap import dedent

# Sent to the client in the handshake. Only what belongs to no single tool: which tool to call, and
# when, is in the tool descriptions, where it reaches the model even when a client drops these
# instructions.

# language=Markdown
INSTRUCTIONS = dedent("""
    This server exposes INSEE (French national statistics) publications from insee.fr: Insee
    Premiere, Insee Analyses, Dossiers, References and Focus, the rapid releases (Informations
    rapides), and the Chiffres-cles summaries.

    Rules that apply to every tool:

    - Never guess a document URL or a publication id. Each is opaque and must come from a discovery
      call first -- `search_insee_documents`, `search_insee_conjoncture` or `search_insee_chiffrecle`.
    - The data is French. Search with French keywords and rich synonyms.
    - An empty result is a valid answer, not a failure. It usually means the filters were too narrow.
    - This server publishes insee.fr only: reports, rapid releases and headline figures. It is not
      the place for granular series or for vocabulary and nomenclature lookups.
""").strip()
