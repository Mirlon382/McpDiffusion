# MCP-layer review against the FastMCP 4 docs

Date: 2026-11-01. Reviewed: `src/mcpdiffusion/` at HEAD `c4ca05c` plus the P0 working-tree
changes (typed lifespan context, rebuilt test suite, this document). Environment: FastMCP
**4.0.0** as pinned by `uv.lock`, Python 3.14 runtime / 3.12 target, MCP Python SDK v2.

Method: every FastMCP-facing module was checked against the official docs through the
connected `fastmcp-docs` MCP server, and each claim was additionally confirmed against the
*installed* package (`inspect.signature` / import probes), because gofastmcp.com tracks a
newer release than the pinned one. Where a docs claim could only be true of a newer
version, it is called out. Page paths below are docs-site paths (e.g. `/servers/tools`).

Verdict up front: **the adoption the refactor report claims is real.** The layer arrived
already FastMCP-4-native; nothing hand-rolled FastMCP features was found left behind. This
pass verified each surface, kept what was right, paid the one piece of debt CLAUDE.md still
owed (untyped lifespan accessors), replaced the lying test suite, and found no new bug in
the MCP layer itself.

---

## 1. Tool declaration and docstring descriptions

**Code.** Every tool is a plain function under `tools/<source>/`, registered with
`mcp.add_tool(fn)` from `tools/__init__.py:register_tools`, behind per-family enable flags.
Tool descriptions come from the function docstrings; every
parameter description comes from `Annotated[..., Field(description=...)]` aliases in
`models/`. `config/tool_metadata.py` (the old redundant metadata layer) is gone, confirming
CLAUDE.md's finding.

**Docs.** `/servers/tools` (~line 40): the decorator path "parses the function's docstring
for the tool description and, if present, per-parameter descriptions". `/servers/tools`
(~323–348, "Docstring Descriptions", new in 3.2.4): Google/NumPy/Sphinx are all parsed;
explicit `Annotated[x, "..."]` or `Field(description=...)` **takes precedence** over
docstring-derived parameter text, "so adoption can be done incrementally". The repo's split
(docstring for the tool, Field for the parameters) is therefore exactly the documented
hybrid, not a half-migration.

**Installed confirmation.** `FastMCP.add_tool(tool: Tool | Callable[..., Any]) -> Tool`
exists in 4.0.0. Conditional registration via `add_tool` is the documented non-decorator
route; the flag-gating comment in `tools/__init__.py` (unregistered = the only "disabled"
the protocol guarantees) is sound.

**Status: correct, unchanged. Now tested** by `tests/test_mcp_layer.py`: `TestRegistration`
asserts the twelve names; `TestPublishedSchemas` asserts each description is derived from the
function docstring, every published parameter carries a description, and injected parameters
are absent from every schema; `TestFlagGating` asserts disabled families are absent rather
than hidden.

## 2. Lifespan

**Code.** One `@lifespan` function (`build_lifespan` in `lifespan/__init__.py`) composing
four `@asynccontextmanager` fragments through an `AsyncExitStack`, yielding one merged dict.

**Docs.** `/servers/lifespan`: `@lifespan` + `from fastmcp.server.lifespan import lifespan`
is the documented entry point; "the dict you yield becomes the lifespan context,
accessible from tools [via `ctx.lifespan_context`]"; existing `@asynccontextmanager`
lifespans "still work" (documented backwards-compatibility); dict fragments compose with
`|`.

**Status: correct; one real flaw fixed.** The composition choice — an exit stack rather
than the `|` operator — is *justified*, not overengineered: `|` merges the context dicts,
but insee.fr and Melodi must share **one** Elasticsearch client, and there is no documented
way to feed one lifespan's value into another's construction. The fragments stay raw
`@asynccontextmanager` because they take constructor arguments; the merged context is what
`@lifespan` yields. What was wrong was what CLAUDE.md already flagged: `ctx.lifespan_context`
is untyped (`Any`), so the `Depends` accessors indexed a `dict[str, Any]` with string keys
no editor could check. This pass introduced **`InseeContext` / `MelodiContext` /
`RmesContext` TypedDicts** next to the lifespans that build them, an **`AppContext(total=False)`**
at the composition root documenting every key the server can yield, and **`cast(...)`** at
each `Depends` accessor. TypedDict and `cast` are runtime no-ops: zero behaviour change,
which the rebuilt suite confirms. The accessors themselves are *not* replaced by
`fastmcp.dependencies.Depends`-only style — CLAUDE.md's verified note stands: `Depends` is
the injection mechanism (which the repo does use); the untyped `lifespan_context` accessor
was the debt, and it is now paid.

## 3. Context and dependency injection

**Code.** Tools take services as `Service = Depends(get_service)` defaults; the providers in
`dependencies/` use `ctx: Context = CurrentContext()`. No tool declares `ctx` at all today
(none logs to the client or reports progress), which is allowed.

**Docs.** `/servers/dependency-injection`: "declare a parameter with a recognized type
annotation or a dependency default value"; `CurrentContext()` is the *explicit* form of the
documented DI ("Both approaches work identically"); the page's note confirms
"dependency parameters are automatically excluded from the MCP schema — clients never see
them".

**Installed confirmation.** `fastmcp.dependencies.Depends` / `CurrentContext` importable in
4.0.0; exclusion verified behaviourally (see §1's tests).

**Status: correct, unchanged.** The repo's choice of the explicit `CurrentContext()` form
matches the docs' equivalence statement; ruff's `extend-immutable-calls` entry for
`Depends`/`CurrentContext` is the right way to keep B008 from misreading the markers.

## 4. Middleware

**Code.** `server.py` adds, in order: `ErrorHandlingMiddleware(transform_errors=False,
include_traceback=True)`, `SlidingWindowRateLimitingMiddleware(max_requests=…,
window_minutes=…, get_client_id=resolve_client_host)`, `TimingMiddleware()`,
`LoggingMiddleware()`.

**Docs.** `/servers/middleware` (Execution Order, ~49–65): "Middleware executes in the
order added… first middleware runs first on the way in and last on the way out… Place
**error handling early** so it catches exceptions from all subsequent middleware. Place
**logging late** so it records the actual execution" — `server.py` matches this exactly,
including the repo's own comment. Rate limiting (~514–526): `SlidingWindowRateLimitingMiddleware`
with `max_requests`/`window_minutes` is the documented precise-window limiter, and
`get_client_id` is the documented per-client keying hook; the hand-rolled middleware and
the `limits` dependency CLAUDE.md flagged as reimplementation are gone, as are the `limits`
env vars. `LoggingMiddleware(include_payloads=…)` truncates rather than redacts and defaults
to `False` — left off, per `.claude/rules/logging.md`.

**Installed confirmation (4.0.0 signatures).** `ErrorHandlingMiddleware(logger,
include_traceback, error_callback, transform_errors)`; `SlidingWindowRateLimitingMiddleware(
max_requests, window_minutes, get_client_id: Callable[[MiddlewareContext], str | Awaitable[str]])`
— `utils/client_host.py:resolve_client_host(_context: MiddlewareContext) -> str` matches the
hook's declared type exactly.

**Status: correct; ordering is now tested.** `tests/test_server_boot.py` asserts the live
`mcp.middleware` list is `[DereferenceRefsMiddleware (FastMCP's own), ErrorHandling,
SlidingWindow, Timing, Logging]`. One design detail worth recording: the rate-limit key
resolver calls `fastmcp.server.dependencies.get_http_request()` and falls back to a shared
`"unknown"` bucket outside HTTP — unit-tested in `tests/test_client_host.py`. Behind the
reverse proxy this is why `TRUSTED_PROXY_HOSTS` exists as a setting; widening it lets a
caller forge its key (documented in `.env.example`).

## 5. Error handling

**Code.** One contract type `AppToolError(ToolError)` with a closed `StrEnum` `ErrorCode`,
raised by services, never built in tools; translation of Elasticsearch failures happens
once at the boundary (`errors/elasticsearch_tool_error_handler.py`); `mask_error_details=True`
on the `FastMCP(...)` constructor; `ErrorHandlingMiddleware(transform_errors=False)`.

**Docs.** `/servers/tools` (~829–857): "`mask_error_details=True` … only error messages from
`ToolError` will include details, other exceptions will be converted to a generic message";
the page's inline note: "Error messages from ToolError are always sent to clients,
regardless of the mask setting". `transform_errors=True` would promote tool failures to
JSON-RPC protocol errors — the repo disables it deliberately, which preserves the
`is_error` + `content[0].text` contract `.claude/rules/error.md` describes.

**Status: correct, and now enforced by tests both ways.** `TestInseeSearchTools` asserts a
typed `AppToolError` reaches the caller verbatim (`[BACKEND_UNAVAILABLE, retryable]` prefix)
while an unexpected `RuntimeError` fails the call *without* leaking its text — the masking
promise is now observable, not just configured. The translator's two-family catch
(`elastic_transport.TransportError` vs `elasticsearch.ApiError`, which do not subclass each
other) and its no-host-leak rule are covered in `tests/test_errors.py`, including a
constructed real `ApiError` per status code (404/400/401/403/5xx/other).

## 6. HTTP deployment and host/origin protection

**Code.** `mcp.http_app(host_origin_protection=True, allowed_hosts=settings.allowed_hosts,
allowed_origins=settings.allowed_origins)`, served by uvicorn with `proxy_headers=True`,
`forwarded_allow_ips=settings.trusted_proxy_hosts`.

**Docs.** `/deployment/http` (~111–121): the strict-mode example is exactly this call
shape; (~151): `True` enforces, `False` (the default) means "FastMCP then provides no
Host/Origin validation or DNS-rebinding protection", `"auto"` is the localhost heuristic —
the repo's comment "enforced rather than auto" states the docs' own tradeoff. (~249):
"Host and Origin protection runs before CORS… Setting `allowed_origins` trusts the request;
it does not emit CORS headers" — consistent with the repo leaving CORS to the deployment.

**Installed confirmation.** `FastMCP.http_app` in 4.0.0 carries `host_origin_protection`,
`allowed_hosts`, `allowed_origins` and `middleware=` — current, as CLAUDE.md verified.
Separately checked: uvicorn 0.52.4's `Config.forwarded_allow_ips` accepts `list[str]`, so
passing the settings list directly is safe (no comma-join needed).

**Status: correct, unchanged.** `booted.app` is asserted to be the built Starlette in the
boot test; the `allowed_hosts == ["*"]` warning stays.

---

## Findings beyond the review checklist

1. **No `# Fixme:` exists in `src/`** — the 131 the report counted were retired by the
   merged branch. This card's "fix the `# Fixme:`s" acceptance was already discharged;
   nothing new surfaced in the MCP layer during this pass.
2. **`run_rmes_sparql`'s blank-query check lives in the tool body**, while
   `.claude/rules/error.md` prefers validation in the Pydantic model. Kept as-is:
   `min_length=1` would neither catch a whitespace-only query nor preserve the
   `[INVALID_INPUT]` message contract (a schema rejection carries FastMCP's validation
   text instead). Flagged, not decided.
3. **`max(1, min(max_rows, MAX_ROW_LIMIT))` in the same tool is redundant** with the
   schema's `ge=1/le=MAX_ROW_LIMIT` — harmless defence in depth, left alone.
4. **`USER_AGENT = "McpDiffusion/0.1.0"`** (in `lifespan/rmes.py` and `lifespan/melodi.py`)
   encodes a version `pyproject.toml` already owns — drift is a matter of time. Proposed
   fix, not applied (behaviour-neutral but touches identity sent to a third party): derive
   it with `importlib.metadata.version("mcpdiffusion")` *inside* the lifespan (startup, not
   import, respecting the no-I/O-at-import rule), or move it to `Settings` if operators
   should control it. Maintainer's call.
5. **The pinned FastMCP is 4.0.0 while the docs describe a newer release line.** Every API
   this review cites was verified against the installed package, so nothing here silently
   depends on a newer surface. Bumping `uv.lock` is a deliberate non-action for this card.
6. **Documentation drift (reported, not followed):** `docs/report.md` §"Known gaps" is
   accurate — README/SKILL still describe the pre-refactor tree. `docs/project.md`'s tool
   descriptions predate the renames. The 12 current names are now pinned by
   `tests/test_server_boot.py`, which will fail loudly if one changes — the live consumer
   in `mcpgateway/` hardcodes them.
7. **The `RESOURCE_QUERY_*` constants** in `graph_store_service.py` are exempt from the
   no-magic-numbers rule by the report's own logic (a fixed internal query the caller
   cannot size, values matching the tool's published bounds); the comment at their
   definition says so. Left.

## Deliberately left in place

- All 8 `# Business rule:` markers, untouched and un-decided (homepage frozen indicators;
  hand-transcribed theme ids; 4 silent-filter-drop rules in `index_service.py`; MELODI
  fetch-whole-then-filter-years rule).
- No new settings, no new dependency, no new tool, no version bumps.
- The exit-stack lifespan composition (rationale in §2).
- `Depends` as the injection mechanism and `ctx.lifespan_context` as the accessor (docs-
  verified; only their *typing* changed).
- The tool-body blank-query check (§6 finding 2) pending maintainer guidance.

## What changed in the working tree

- `lifespan/{insee,melodi,rmes}.py`: per-source `TypedDict` context fragments + typed yield.
- `lifespan/__init__.py`: `AppContext(total=False)` documenting every yielded key; one
  `cast` at the yield edge.
- `dependencies/{insee,melodi,rmes}.py`: `cast(...)` at each accessor — same runtime, real typing.
- `tests/`: the seven stale auto-generated modules deleted (they imported the deleted junk-
  drawer layout: `mcpdiffusion.config`, `core.middleware`, `infra.sparql`, `register_*`
  wrappers, `RMES_*` names — collection failed at `conftest`); replaced by `fakes.py`,
  `conftest.py`, and six focused modules: `test_settings` (typed loading, startup validator,
  `.env.example` ↔ `Settings` sync in both directions), `test_errors` (message contract,
  closed vocabulary, ES translation matrix, host-leak guard), `test_client_host`,
  `test_melodi_years` (the malformed-row regression), `test_tools_contract` (the published
  schema + call contract of all twelve tools through an in-memory `Client`), and
  `test_server_boot` (the CLAUDE.md boot check as a test: real `server.py` import, lifespan
  boot, middleware order per the docs, env→settings plumbing, end-to-end tool calls).
- `docs/review-mcp-layer.md`: this document.

## Claim → source index

| # | Claim | Docs lookup | Installed-4.0.0 check |
|---|---|---|---|
| 1 | Docstrings parsed for tool + parameter descriptions; explicit Field wins | `/servers/tools` ~40, ~323–348 | — |
| 2 | `mcp.add_tool` registers plain functions | `/servers/tools` | `inspect.signature(FastMCP.add_tool)` |
| 3 | `@lifespan`, yielded dict is the context, `ctx.lifespan_context` documented | `/servers/lifespan` ~1–60 | `from fastmcp.server.lifespan import Lifespan, lifespan` |
| 4 | `@asynccontextmanager` lifespans remain supported (composition rationale §2) | `/servers/lifespan` "Backwards Compatibility" | present |
| 5 | DI via `Depends`/`CurrentContext`; injected params excluded from schema | `/servers/dependency-injection` ~14, ~50–60 | importable |
| 6 | Middleware = order added, first-in-last-out; errors early, logging late | `/servers/middleware` ~49–65 | `FastMCP.middleware` list |
| 7 | `SlidingWindowRateLimitingMiddleware(max_requests, window_minutes, get_client_id)` | `/servers/middleware` ~514–526 | signature match |
| 8 | `ErrorHandlingMiddleware(transform_errors, include_traceback)` | `/servers/middleware` (built-in list) | signature match |
| 9 | `mask_error_details=True`: only `ToolError` messages survive | `/servers/tools` ~829–857 | constructor accepts |
| 10 | `host_origin_protection=True` strict mode; `False` disables; `"auto"` localhost-only | `/deployment/http` ~111, ~151 | `http_app` signature |
| 11 | Host/origin guard runs before CORS; `allowed_origins` trusts, does not add headers | `/deployment/http` ~249 | — |
| 12 | uvicorn accepts `list[str]` for `forwarded_allow_ips` | — (uvicorn, not FastMCP) | `uvicorn.Config.__init__` source |
