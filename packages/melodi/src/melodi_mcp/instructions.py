"""The handshake text this brick sends. It describes MELODI and nothing else."""

from textwrap import dedent

# Sent to the client in the handshake. Only what belongs to no single tool: which tool to call, and
# when, is in the tool descriptions, where it reaches the model even when a client drops these
# instructions.

# language=Markdown
INSTRUCTIONS = dedent("""
    This server exposes MELODI, the INSEE catalogue of detailed statistical datasets, with the
    observations themselves.

    The three tools chain, in this order:

    1. `search_melodi_datasets` -- find the dataset, and the ids of its columns
    2. `search_melodi_modalities` -- turn a term into the modality codes that filter those columns
    3. `get_melodi_observations` -- fetch the filtered rows

    Rules that apply to every tool:

    - Never guess a dataset id, a column id or a modality code. Each is opaque and must come from the
      discovery call that precedes it.
    - The data is French. Search with French keywords and rich synonyms.
    - An empty result is a valid answer, not a failure. It usually means the filters were too narrow.
""").strip()
