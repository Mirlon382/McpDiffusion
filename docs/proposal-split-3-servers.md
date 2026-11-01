# Proposal — split McpDiffusion into three composable MCP servers

Ideation, not a plan of record. Nothing here is decided; the open questions are collected in §6.

The finality is the gateway (`mcpgateway`), but that is the *end state*, not the design driver. The design
driver is stated as: **three bricks, each usable alone, any subset usable together.** The gateway is one of
several ways to hold the bricks together.

---

## 1. What is in the box today

12 registered tools, 4 families, one HTTP endpoint, one FastMCP app.

| Brick | Tools | Needs at runtime | Third-party deps actually imported |
|---|---|---|---|
| **insee.fr** (5) | `search_insee_documents`, `search_insee_conjoncture`, `search_insee_chiffrecle`, `get_insee_document`, `get_insee_homepage` | Elasticsearch index `produit` **+** live HTML fetch of insee.fr (`GET_INSEE_HOMEPAGE` needs neither) | `elasticsearch`, `httpx`, `trafilatura`, `bs4` |
| **MELODI** (3) | `search_melodi_datasets`, `search_melodi_modalities`, `get_melodi_observations` | Elasticsearch indices `melodi_datasets`, `melodi_columns` **+** REST `api.insee.fr/melodi/data` | `elasticsearch`, `httpx` |
| **RMES** (3) | `search_rmes_graphs`, `describe_rmes_resource`, `run_rmes_sparql` | SPARQL `rdf.insee.fr/sparql` only — **no Elasticsearch** | `httpx` |
| *cross-cutting* (1) | `send_feedback` | nothing (log sink) | — |

Size: 4 070 LOC under `src/`, 2 044 LOC of (unreviewed) tests. 31 settings, 58 modules.

### The seam is already ~80% cut

The last refactor moved everything into per-source packages on purpose:

```
tools/<source>/        services/<source>/     models/<source>.py
data/<source>/         lifespan/<source>.py   dependencies/<source>.py
```

**Everything that is genuinely per-source is already in a per-source file.** What is *not* per-source today is
a short list, and that list is the entire design problem:

| Shared today | Why it is shared | Fate under a split |
|---|---|---|
| `settings.py` (one `Settings`, 31 fields) | one process reads all three families | split into per-brick settings + a common HTTP-server block |
| `logging.py` | one process, one log config | to the core |
| `errors/error.py` (`AppToolError`, `ErrorCode`) | one error contract for the whole family | to the core — keep one vocabulary across bricks |
| `errors/elasticsearch_tool_error_handler.py` | ES-only | core, optional extra |
| `utils/client_host.py` (rate-limit key) | one rate limiter | to the core |
| `server.py` (app + 4 middlewares + host guard + uvicorn) | one app | **the core's `create_server()` factory** — would otherwise be copy-pasted 3× |
| `lifespan/__init__.py` (composition root) | one composition root | becomes *the aggregate's* only real content |
| `lifespan/elasticsearch.py` | insee + melodi share one cluster | core factory, instantiated per brick (see §3-C) |
| `services/feedback.py` + `models/feedback.py` + `tools/send_feedback_tool.py` | cross-cutting | owner undecided (see §3-G) |

---

## 2. What "lego" has to mean concretely

A brick is a brick only if it is interchangeable with its siblings at the connector. Checklist to hold the
design to:

1. **Same connector**: HTTP MCP at a path, same handshake shape, same error vocabulary, same log format,
   same health route. A client that can call one can call all three.
2. **No shared runtime state**: own process, own port, own env, own rate-limit bucket, own failure domain.
3. **Honest dependencies**: a brick declares only what it uses. RMES must not drag in the Elasticsearch
   driver, `trafilatura`, `bs4`, `lxml`.
4. **Composable in any subset**: {insee}, {melodi}, {rmes}, {insee,melodi}, all three — plus the current
   all-in-one, which becomes an *assembly* rather than a fourth codebase.
5. **Knows no sibling**: a brick must not import another brick. Cross-brick knowledge, if any, is data
   (see §3-F).
6. **Own instructions**: the handshake text is per-brick, not "three sources" boilerplate.

---

## 3. Design axes

Each axis: the options, then what I would pick and why.

### A. Repo and packaging shape

- **A1 — one distribution, three entrypoints** (`python -m mcpdiffusion.insee`). Least churn, but not real
  lego: one lockfile, one image, `elasticsearch` installed for RMES.
- **A2 — uv workspace, one repo: `insee-mcp`, `melodi-mcp`, `rmes-mcp` + shared `diffusion-mcp-core`,
  three entrypoints, three images built from one Dockerfile with per-package dependency groups.** ← **pick**
- **A3 — three repos + a published core.** True release independence; the core becomes a coordination tax
  and version skew, and the core API is not settled yet (see §5-P0).

Why A2: it buys A3's dependency isolation and deployability without freezing an interface that is still
moving. The repo just finished a large refactor and the FastMCP-4 adoption is explicitly unfinished, so the
shared layer will change. A monorepo makes a cross-brick refactor one commit; three repos make it three PRs
plus a release dance.

### B. The core ("the stud")

Rule to keep it honest: **the core holds only what would otherwise be *literally identical* in ≥2 bricks.**
Anything identical in one brick stays in that brick. Candidate contents, all taken from §1's shared list:

- `create_server(name, instructions, lifespan, register, settings)` — app + the 4 middlewares + `http_app`
  host/origin protection + the `/health` custom route + the uvicorn runner.
- `ServerSettings` base (host, port, allowed_hosts/origins, trusted_proxy_hosts, rate limit, log_level) that
  each brick's `Settings` extends with its own fields.
- `AppToolError` / `ErrorCode`, logging setup, `resolve_client_host`.
- `elasticsearch_client(...)` factory + the ES error translator, behind an optional extra.
- **Explicitly not in the core**: any service, model, or data table belonging to one source.

### C. The Elasticsearch question

insee and MELODI share one cluster and today one client. Options: (C1) each brick opens its own connection to
the same cluster; (C2) a fourth "ES provider" brick; (C3) the core owns the *factory*, each brick owns the
*lifecycle*.

**Pick C3 (= C1 with the code shared).** A connection is cheap and the two bricks read disjoint indices; a
fourth brick would be a dependency of two bricks, which is the opposite of lego. Consequence to accept
knowingly: one cluster going down now takes out exactly two bricks instead of one server — which is the
failure isolation we wanted anyway.

The real win: the shared driver becomes optional, so `rmes-mcp` installs `fastmcp`, `httpx`, `uvicorn`,
`pydantic-settings`, `python-dotenv` and nothing else — and needs no infrastructure at all, so it can be
deployed anywhere, or run locally over stdio.

Side finding while inventorying deps: `requests` is declared in `pyproject.toml` and imported **nowhere**;
`starlette` is declared and imported nowhere directly; `lxml` is declared and only reached through
`trafilatura`. The split is a free opportunity to make each brick's dependency list mean something.

### D. Composition — the three ways "together" can mean

1. **Gateway (primary, the finality).** Three registry entries. The gateway already gives per-brick
   `timeout`, `max_concurrency`, `cache_ttl`, per-brick health and a `domain` grouping. It also *masks* the
   catalogue behind `tool_search` (`max_results: 5`), so going from 12 tools to 12 tools spread over 3
   servers costs the calling agent nothing in context. Splitting is cheaper today than it would have been
   before the gateway existed.
2. **Assembly in-process.** FastMCP's `mount()` creates a live link with component prefixing, forwards
   `custom_route`s to the parent, and layers middleware (parent first, then the child's own). Verified in
   the FastMCP docs, not remembered. So the current all-in-one becomes ~20 lines: mount the three, no
   duplicated tool code. *(The prefix keyword differs across doc versions — `prefix=` vs `namespace=`;
   confirm against the installed version before writing it.)*
3. **Direct.** A client points at one brick's `/mcp`. This is what "independently" means and it needs no
   work beyond §2.

### E. Naming and the gateway prefix

Today every tool is self-prefixed (`search_insee_documents`) because one server hosts three sources. After the
split, the gateway adds its own prefix, and `insee_search_insee_documents` stutters.

- **E1** keep names as-is → stuttering at the gateway, zero churn in docstrings/`SKILL.md`/the gateway guide.
- **E2** drop the source prefix inside each brick (`search_documents`, `search_datasets`, `run_sparql`) →
  clean gateway names, but a rename touching every cross-reference, and direct/assembled use loses the
  disambiguating prefix.
- **E3** keep the code names, and let the *gateway* decide how it presents them (naming the bricks `insee`,
  `melodi`, `rmes` yields exactly the E2 names with no rename at all).

**Lean E3/E1**: the tool name is part of a published contract, and the two things that consume it
(`SKILL.md`, the gateway guide) are outside this repo. If the stutter matters, it is a gateway-presentation
problem, and E3 solves it for free.

### F. Cross-brick references in tool descriptions (the real coupling)

Counted, not guessed: **4 of 11 source tool files name a tool belonging to another source**, 10 mentions
total.

- `search_insee_documents` → `run_rmes_sparql`, `search_melodi_datasets`
- `search_insee_chiffrecle` → `search_melodi_datasets`
- `search_melodi_datasets` → `run_rmes_sparql`, `search_insee_documents`, `get_insee_homepage`
- `get_melodi_observations` → `run_rmes_sparql`

(All RMES descriptions reference only RMES — that brick is already clean.)

Plus the handshake `INSTRUCTIONS`, which says "this server exposes three sources" and carries the rule that
a description may point at a tool you do not have.

Options: (F1) delete cross-brick mentions per brick; (F2) keep them as templates resolved at registration
from a declared sibling prefix; (F3) keep them verbatim and let the handshake rule + the gateway's
catalogue/guide carry the routing.

**Pick F3, and move the routing story to the gateway guide.** Reason: a commit in this repo's history
(`e65631c`) deliberately *restored* routing guidance into tool descriptions — deleting it would undo a
decision that was made with a reason. But a brick cannot know the prefix it will be reached under, and
guessing is worse than silence. The gateway is the only component that sees all bricks, and it already
has the exact mechanism: `catalog://guide` and `guide-ssp.md`, which today chains `geodata` and
`mcpdiffusion` by name. Cross-source routing belongs where the cross-source view lives.

Cost to state plainly: a brick used *standalone* keeps hints that name tools it does not have. That is what
the existing handshake rule is for; keep it, per brick.

### G. Who owns `send_feedback`

Three copies of a log-only tool mean three feedback streams to read. Alternatives: each brick registers it
(stream fragments, but the tool stays next to what it reports on), or it moves to the gateway (one stream,
but the gateway is not this repo). **This is a policy question, not a technical one — flagging it rather
than deciding it.** If it stays per brick, the core can provide it as one line, and the log entry should
carry the brick name.

### H. Health and lifecycle

`server.py` exposes no health route today, and the known gaps list already flags that `k8s/` declares no
probes because Kubernetes ignores the Docker `HEALTHCHECK`. The gateway probes its upstreams
(`probe_interval_seconds`, `failure_threshold: 2`).

Cheap fix that lands naturally with the split: the core's factory registers `@mcp.custom_route("/health")`
(verified pattern) returning at minimum the brick name and version, and ideally which of the brick's own
backends the lifespan actually opened. Then every brick is probeable by the gateway *and* by k8s, closing
a gap that exists today.

### I. Cross-cutting policies that need an assigned owner

Splitting multiplies the places a policy is enforced. Today `server.py` owns all of them:

| Policy | Brick-owned | Gateway-owned |
|---|---|---|
| rate limiting | per-brick bucket (100/min × 3 = 300/min for the family) | one global bucket, but no limit exists for that today |
| host/origin protection | each brick checks its own hostname | gateway is the only public hostname |
| auth | none today | not this repo's concern |

Lean: bricks keep their own guards (they are separately reachable, defence in depth is cheap, and the core
makes it a default), and the effective family-wide rate limit becomes an explicit decision rather than an
accident of multiplication.

### J. Deployment shape

- **Images**: one `Dockerfile`, three targets/packages, per-brick dependency groups. Not one image with an
  env-selected entrypoint — that would ship `elasticsearch` and `trafilatura` to the RMES brick and waste
  the whole dependency argument.
- **compose**: one service per brick (+ the existing ES service and inspector), ports 8001/8002/8003.
- **k8s**: three deployments, or one pod with three containers. Either way each brick gets the probe it
  does not have today.
- **One source of truth for the bricks' metadata**: a small `bricks.yaml` (name, title, tags, domain, URL
  pattern, dependency group) from which the compose services, the per-brick `.env.example`, and a *registry
  fragment for the gateway* are generated. A brick that ships its own deployment snippet is a brick that
  can be picked up without editing a central file — which is also exactly how the gateway's registry wants
  to be fed.

---

## 4. Proposed layout

```
McpDiffusion/
├── pyproject.toml                  # workspace root
├── bricks.yaml                     # the metadata single source of truth (§3-J)
├── packages/
│   ├── core/                       # diffusion-mcp-core — the stud
│   │   └── src/core/{app.py, settings.py, errors/, logging.py, es.py, feedback.py, health.py}
│   ├── insee/    src/insee_mcp/{server.py, tools/, services/, models/, data/, lifespan.py, dependencies.py, settings.py, instructions.py}
│   ├── melodi/   src/melodi_mcp/{…}
│   └── rmes/     src/rmes_mcp/{…}
├── apps/
│   └── aggregate/                  # the current all-in-one, now ~20 lines: mount the three
└── tests/                          # per package, plus one that boots each brick (the gap CLAUDE.md flags)
```

Prereq the code already satisfies: no test currently imports the app, so nothing breaks when the entrypoints
multiply — but a "boots and lists its tools" test per brick becomes mandatory, because that is the only
thing that proves a brick is a brick.

---

## 5. Migration, in shippable phases

**P0 — settle the shared layer first.** The current mission (finish the FastMCP-4 adoption, review the MCP
layer against the docs) changes exactly the code the core will contain. Extracting a core out of a moving
layer means extracting it twice. Do not split before this settles.

**P1 — extract the core in place.** No behaviour change, no new entrypoint, `mcpdiffusion` keeps working.
Proof: the client boot check + a green suite.

**P2 — three entrypoints.** Each imports its own family + the core. `tools/__init__.py`'s
`register_tools(mcp, settings)` is already the right shape for this — each brick gets its own `register()`.

**P3 — the aggregate becomes an assembly.** Mount the three. The `ENABLE_*_TOOLS` flags and the
"some families disabled" branches in `lifespan/__init__.py` collapse into "which bricks am I mounting".

**P4 — gateway integration.** Three registry entries (one `domain`, e.g. `diffusion`, so the family still
reads as one family to the agent), `enabled: true` alongside the still-live `mcpdiffusion` during a parallel
run, and `guide-ssp.md` updated — its *démarches* hardcode `mcpdiffusion_*` tool names, so the guide is the
thing that breaks first and the thing that must be rewritten with the new names and the new cross-server
routing.

**P5 — retire the aggregate** (or keep it as the "I do not run a gateway" entry). Both are legitimate; the
aggregate now costs nothing to keep alive because it is only an assembly.

Each phase leaves the gateway working, which is the same lego discipline applied to the migration itself.

---

## 6. Decisions

All eight questions are answered. Where a decision contradicts a "pick" written above, **the decision wins**;
the picks are left in place as the reasoning that led there.

| # | Question | Decision |
|---|---|---|
| 1 | Repo shape (§3-A) | **A2** — uv workspace, one repo, three distributions + `core`. |
| 2 | Who owns `send_feedback` (§3-G) | **The gateway.** The bricks stop registering it; the tool moves out of this repo's brick surface. |
| 3 | Rate limiting (§3-I) | **Per brick, specific.** Each brick carries its own limit; no family-wide bucket. |
| 4 | Tool names (§3-E) | **Stay exactly as they are** (`search_insee_documents`, …) — simplicity over gateway-presentation polish. Zero renames, so `SKILL.md` fragments and the gateway guide keep their vocabulary. |
| 5 | Cross-brick routing text (§3-F) | **F3, in its stronger form**: the descriptions are *cleaned* of other servers' tools (MELODI's RMES mentions disappear, etc.) and that routing prose is **moved into a gateway resource** — the gateway guide. Bricks mention only their own tools. |
| 6 | Domain grouping | **One domain, named `Insee`**, and the bricks carry **meaningful tags/metadata** so the catalogue can group and filter them usefully. |
| 7 | Does the aggregate survive (§5-P5) | **Yes, for now** — it is the vehicle for user-facing presentations of the split. |
| 8 | `SKILL.md` shape | **One document per brick** (it is written for the LLM client; regeneration splits it along the brick boundary). |

Consequence for §5: P3 keeps the aggregate as an assembly rather than a codebase, P5 does *not* retire it, and a
new P6 (below) produces the presentation material.

## 7. Verified vs assumed

Verified by reading this repo: the tool inventory, per-source module layout, the shared-module list, the
dependency usage (`requests`/`starlette`/`lxml` unused directly), the cross-brick mentions and their count,
`settings.py`'s validator coupling, the gateway's `tool_search`/`catalog`/`health`/concurrency behaviour and
the `mcpdiffusion_*` names hardcoded in `guide-ssp.md`.

Verified against the FastMCP docs (via the `fastmcp-docs` server, not from memory): `mount()` semantics —
live link, component prefixing, `custom_route`s forwarded to the parent, middleware layering — and
`@mcp.custom_route("/health")`. **Not yet verified**: the exact prefix keyword on the installed version
(`prefix=` vs `namespace=`), and whether `ENABLE_*`-style flag filtering has a built-in equivalent that
makes the hand-rolled disable branches unnecessary.
