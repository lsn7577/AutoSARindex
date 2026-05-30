<a href="https://www.infineon.com">
<img src="./assets/images/Logo.svg" align="right" alt="Infineon logo">
</a>

# autosarindex

Agent-first indexing for AUTOSAR standard documents.

## What it does

`autosarindex` is meant to be handed to an external agent in three parts:

1. **Enriched ToC JSON** - Hierarchical section tree with page ranges, pre-computed breadcrumbs, boilerplate flags, AUTOSAR requirement IDs, normative keyword hints, referenced AUTOSAR documents, and a preamble (pages 1-2 raw text) for agent orientation
2. **Page-matched text file** - Full document text with `--- PAGE N ---` markers aligned to the JSON, with column-aware reading order for two-column layouts
3. **Tool surface** - Section reading, text search, page rendering, and optional table markdown extraction for edge cases

All page numbers are **1-indexed** across the JSON, the text file markers, and
`inspect_page(page=...)`.

The library exposes `create_autosar_tools_server()`, which packages
artifact-building, ToC/text access, text search, and `inspect_page` as an
MCP/tool-server surface the agent can mount. The older `datasheetindex` package
and `create_datasheet_tools_server()` names remain as compatibility aliases.

## Philosophy

The library doesn't interpret AUTOSAR requirements by itself. The agent does.
All intelligence lives in the agent; the library provides the best possible
starting context and the right tools for edge cases.

## Supported documents

`autosarindex` is designed for AUTOSAR standard PDFs such as SWS, RS, SRS, PRS,
and TPS documents. It still works as a generic PDF indexer and keeps the legacy
datasheet-compatible API while the project transitions.

When a source looks like AUTOSAR material, the JSON artifact includes:

- `document_type: "autosar"`
- `autosar_metadata` with detected title, document ID, release, version, status,
  and platform
- `autosar_requirements` with a document-level list of requirement IDs
- an `autosar_requirements.index` lookup keyed by requirement ID, with
  occurrence counts, pages, semantic kind counts, specific sections, and short
  snippets for definition/reference/traceability/change-history hits
- ToC-node enrichments such as `autosar_section_type`, `requirement_ids`,
  `requirement_count`, `requirement_occurrence_summary`,
  `normative_keywords`, and `referenced_documents`

This preserves the existing page-matched text, search, section reading, and
visual inspection tools while adding AUTOSAR-specific navigation metadata.

## Links

- [Infineon Developer Community](https://community.infineon.com/) - forums and
  knowledge base
- [Infineon Developer Center](https://softwaretools.infineon.com/) - tools and
  software packages
- [How to contribute](./CONTRIBUTING.md)
- [Code of Conduct](./CODE_OF_CONDUCT.md)
- [Support](./SUPPORT.md)
- [License](./LICENSE)

## Setup

```bash
uv sync
uv run pre-commit install
```

Optional integrations:

```bash
# LLM fallback / summaries (`create_llm_client`, `--model`, and automatic
# low-quality ToC fallback when credentials are available)
uv sync --extra llm

# Local MCP server testing (`autosarindex-mcp-server`)
uv sync --extra mcp

# MCP server handoff to a consuming agent (`create_autosar_tools_server`)
uv pip install claude-agent-sdk
```

For LLM-backed ToC fallback and summaries, configure `LITELLM_BASE_URL` and
`LITELLM_MASTER_KEY` (see `.env.example`).

`claude-agent-sdk` is only required if you want the MCP/tool-server handoff.
The `mcp` extra is only required if you want to run a local stdio/HTTP MCP
server from this repository.

## Development

```bash
uv run pytest              # run tests
uv run ruff check src/     # lint
uv run ruff format src/    # format
uv run ty check            # type check
```

The pre-commit pytest hook runs the fast subset only:
`uv run pytest -q -m "not integration and not real_pdf"`. Run
`uv run pytest` for the full suite, including real-PDF and integration tests.

## Input sources

`AutosarIndex` and `AutosarTools` accept either:
- a local PDF file path, or
- an `http(s)` URL pointing to a PDF document.

## Hand the MCP server to an agent

```python
from autosarindex import AutosarIndex, create_autosar_tools_server

artifacts = AutosarIndex("AUTOSAR_SWS_COM.pdf").build(output_dir="output")
autosar_tools_server = create_autosar_tools_server()

# Pass autosar_tools_server into your agent runtime's MCP server configuration.
# The exact wiring depends on the host agent framework; this server object is the
# concrete handoff point from autosarindex to the agent.
agent = SomeAgentRuntime(
    mcp_servers={"autosar-tools": autosar_tools_server},
    system_prompt=build_prompt_from(artifacts),
)
```

If you want direct Python access instead of an MCP server, use `AutosarTools`
to build artifacts, search text, and call `inspect_page()` on the bound
instance.

```python
from autosarindex import AutosarTools

with AutosarTools("AUTOSAR_SWS_COM.pdf") as tools:
    artifacts = tools.build_document(output_dir="output")
    ids = tools.list_requirements(prefix="SWS_Com_", max_results=50)
    context = tools.get_requirement_context("SWS_Com_00001")
    matches = tools.search_text("SWS_Com_00001")
    section_text = tools.get_section_text(12, 14)
    image = tools.inspect_page(
        page=12,
        region={"top": 0.15, "bottom": 0.55, "left": 0.05, "right": 0.95},
    )
```

The optional `region` crop uses percentages from `0.0` to `1.0`.

## Run a local MCP server

You can run the local MCP server directly from the repository. It exposes these
tools for the bound PDF source:

- `build_document` - build and save the `.json` / `.txt` artifacts
- `list_requirements` - list requirement IDs without returning the full JSON
- `get_requirement_context` - return pages, sections, kind counts, and snippets
  for one requirement ID
- `get_section_text` - return extracted text for a page range from the latest build
- `search_text` - find page-aware text snippets in the latest build, even when
  labels wrap across lines or table values interrupt the phrase
- `inspect_page` - render a page image when visual confirmation is needed
- `extract_table_markdown` - re-extract a page as layout-aware Markdown when
  optional layout dependencies are installed

`build_document` returns a compact manifest rather than the full JSON artifact,
so initial tool calls stay small even for large SWS documents. Build once, then
use `list_requirements` and `get_requirement_context` for requirement-centric
questions. Use `get_section_text`, `search_text`, and `inspect_page` when you
need wider context or visual confirmation.
`search_text` prefers exact matches, then falls back
to whitespace-normalized and ordered-token matching for line-wrapped table
rows.

```bash
# stdio transport (for Claude Code or another MCP client)
uv run --extra mcp autosarindex-mcp-server

# then call build_document(output_dir="output") from the MCP client
```

You can also expose it over HTTP:

```bash
# streamable HTTP transport (useful with MCP Inspector)
uv run --extra mcp autosarindex-mcp-server \
  --transport streamable-http --port 8000
```

With `streamable-http`, the default MCP endpoint is
`http://127.0.0.1:8000/mcp`.

This local server is for direct MCP testing. If you need an in-process SDK
server object inside another Python runtime, use
`create_autosar_tools_server()` instead; it exposes the same tool surface.

## Python API

```python
from autosarindex import AutosarIndex, build_batch

artifacts = AutosarIndex("AUTOSAR_SWS_COM.pdf").build(output_dir="output")

batch_result = build_batch(
    ["AUTOSAR_SWS_COM.pdf", "AUTOSAR_SWS_PDUR.pdf"],
    output_dir="batch-output",
)
```

In batch mode, output filenames are suffixed as needed to keep them unique when
multiple inputs would otherwise resolve to the same stem.

## CLI

```bash
# Local file
autosarindex build path/to/AUTOSAR_SWS_COM.pdf --output-dir output

# Remote URL
autosarindex build https://example.com/AUTOSAR_SWS_COM.pdf --output-dir output

# With explicit LLM model for ToC fallback and summaries
autosarindex build AUTOSAR_SWS_COM.pdf --model gpt-4.1 --include-summaries
```

By default, `autosarindex` first uses native PDF ToC extraction. If ToC
quality is low, it automatically attempts LLM fallback with the default model
(`gpt-4.1`) when LLM credentials are available. Pass `--model` to choose the
LLM model explicitly; `--include-summaries` requires `--model`.

## Validation and token efficiency

The AUTOSAR requirement index was validated against representative documents in
the workspace:

| Document | Pages | Requirement IDs | Requirement occurrences |
| --- | ---: | ---: | ---: |
| `AUTOSAR_RS_ECUConfiguration.pdf` | 33 | 53 | 112 |
| `AUTOSAR_SRS_OS.pdf` | 39 | 60 | 120 |
| `AUTOSAR_SWS_OS.pdf` | 335 | 776 | 1188 |

For requirement-centric queries, the intended path is:

1. `build_document`
2. `list_requirements` when discovery is needed
3. `get_requirement_context(requirement_id)`
4. `get_section_text` only when the returned snippets are not enough

Approximate context sizes from the same validation run (`characters / 4` token
estimate):

| Document | Full extracted text | `list_requirements(max_results=20)` | One `get_requirement_context` | Context plus one page |
| --- | ---: | ---: | ---: | ---: |
| `AUTOSAR_RS_ECUConfiguration.pdf` | 13,558 | 104 | 770 | 1,276 |
| `AUTOSAR_SRS_OS.pdf` | 16,856 | 100 | 274 | 808 |
| `AUTOSAR_SWS_OS.pdf` | 153,594 | 101 | 308 | 822 |

This keeps common requirement lookups far smaller than reading the whole PDF
text while preserving the raw page-matched text for audit and fallback.

## Project structure

```
src/autosarindex/       # implementation package and public AUTOSAR API
src/datasheetindex/     # compatibility wrappers for legacy imports
    core/
        structure.py       # ToC extraction + enriched tree JSON
        textfile.py        # PDF -> page-matched text file (column-aware)
        preamble.py        # Pages 1-2 raw text extraction
        quality.py         # ToC quality assessment
        annotations.py     # Footnote and cross-reference enrichment
        boilerplate.py     # Title-pattern boilerplate classification
        autosar_metadata.py # AUTOSAR cover-page metadata detection
        requirements.py    # AUTOSAR requirement enrichment
    tools/
        vision.py          # inspect_page (page -> image)
        registry.py        # MCP/tool-server factory for agent runtimes
    mcp_server.py          # Local stdio/HTTP MCP server entry point
    llm/
        client.py          # LLM client factory
        toc_fallback.py    # LLM-based ToC generation fallback
        summarizer.py      # Optional section summaries
    cli.py                 # CLI entry point
    index.py               # Main indexing class
    models.py              # Data models
```

## License

Licensed under the [MIT License](./LICENSE).

Copyright (c) 2026 Infineon Technologies AG
