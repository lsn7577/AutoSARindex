"""Local MCP server entry point for autosarindex."""

import argparse
import asyncio
import importlib
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, TypedDict

from autosarindex.tools.registry import AutosarTools
from autosarindex.tools.vision import Detail


class Region(TypedDict, total=False):
    top: float
    bottom: float
    left: float
    right: float


@dataclass
class _ServerContext:
    tools: AutosarTools | None = None


def _load_mcp_modules() -> tuple[Any, Any, Any]:
    try:
        return (
            importlib.import_module("mcp.server.fastmcp"),
            importlib.import_module("mcp.server.session"),
            importlib.import_module("mcp.types"),
        )
    except ImportError:
        raise ImportError(
            "mcp is required for local MCP server support. "
            "Install it with: uv sync --extra mcp"
        ) from None


def _preload_layout_model() -> None:
    """Import pymupdf4llm to trigger ONNX model loading at startup.

    The layout model takes ~2s to load. Doing this eagerly at server
    start avoids a long GIL-holding pause on the first tool call, which
    can cause MCP client timeouts.
    """
    try:
        import pymupdf4llm  # noqa: F401
    except ImportError:
        pass  # optional dependency; extract_table_markdown will report the error


def create_local_mcp_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    streamable_http_path: str = "/mcp",
) -> Any:
    """Create a standard MCP server for local stdio/HTTP testing.

    The server starts without a bound PDF. Call ``build_document`` with a
    ``pdf_source`` (local path or URL) to load a document. Calling it again
    with a different source replaces the current document.
    """
    fastmcp_module, session_module, types_module = _load_mcp_modules()
    FastMCP = fastmcp_module.FastMCP
    Context = fastmcp_module.Context
    ServerSession = session_module.ServerSession
    CallToolResult = types_module.CallToolResult
    ImageContent = types_module.ImageContent

    @asynccontextmanager
    async def _lifespan(_server: Any) -> AsyncIterator[_ServerContext]:
        ctx = _ServerContext()
        # Pre-load pymupdf4llm ONNX models so the first extract_table_markdown
        # call doesn't block for ~2s during model initialization.
        await asyncio.to_thread(_preload_layout_model)
        try:
            yield ctx
        finally:
            if ctx.tools is not None:
                ctx.tools.close()

    server = FastMCP(
        name="autosarindex",
        instructions=(
            "Index AUTOSAR standard PDFs. Call build_document FIRST with a "
            "pdf_source (local path or URL) to load a document -- it returns "
            "the full enriched ToC plus AUTOSAR metadata and requirement "
            "summaries when detected. Then use list_requirements and "
            "get_requirement_context for requirement-focused questions, "
            "get_section_text to read page ranges, search_text to locate "
            "keywords, and inspect_page for visual content. You can switch "
            "documents by calling build_document with a new source. When a "
            "table in get_section_text looks garbled, use "
            "extract_table_markdown for a clean Markdown table (cheaper than "
            "inspect_page)."
        ),
        host=host,
        port=port,
        streamable_http_path=streamable_http_path,
        lifespan=_lifespan,
    )

    def inspect_page_tool(
        page: int,
        region: Region | None = None,
        dpi: int | None = None,
        detail: Detail = "medium",
        ctx: Context[ServerSession, _ServerContext] | None = None,
    ) -> Any:
        """Render a PDF page as an MCP image result.

        `detail` defaults to "medium" (100 dpi, ~1150 vision tokens) -- the
        right tier for most agent calls. Bump to "high" (150 dpi, ~2580
        tokens) for footnotes/subscripts/dense schematics, or drop to
        "low" (75 dpi, ~650 tokens) for layout overview. `dpi` is a
        power-user override that wins over `detail` when set.
        """
        if ctx is None:
            raise RuntimeError("MCP context was not provided")

        blocks = ctx.request_context.lifespan_context.tools.inspect_page(
            page, region=region, dpi=dpi, detail=detail
        )
        if len(blocks) != 1:
            raise RuntimeError("inspect_page returned an unexpected content shape")

        block = blocks[0]
        return CallToolResult(
            content=[
                ImageContent(
                    type="image",
                    data=block["data"],
                    mimeType=block["mime_type"],
                )
            ]
        )

    async def build_document_tool(
        pdf_source: str,
        output_dir: str | None = None,
        output_stem: str | None = None,
        include_summaries: bool = False,
        model: str | None = None,
        force_rebuild: bool = False,
        ctx: Context[ServerSession, _ServerContext] | None = None,
    ) -> dict[str, object]:
        """Build and save document artifacts for a PDF source.

        ``output_dir`` is optional; the resolution rules live with
        :meth:`autosarindex.build` (single source of truth).
        """
        if ctx is None:
            raise RuntimeError("MCP context was not provided")
        server_ctx = ctx.request_context.lifespan_context
        # Re-bind to a new PDF if the source changed
        if server_ctx.tools is None or server_ctx.tools.pdf_path != pdf_source:
            if server_ctx.tools is not None:
                server_ctx.tools.close()
            server_ctx.tools = AutosarTools(pdf_source)
        await asyncio.to_thread(
            server_ctx.tools.build_document,
            output_dir=output_dir,
            output_stem=output_stem,
            include_summaries=include_summaries,
            model=model,
            force_rebuild=force_rebuild,
        )
        return server_ctx.tools.get_artifact_manifest()

    def get_section_text_tool(
        start_page: int,
        end_page: int,
        ctx: Context[ServerSession, _ServerContext] | None = None,
    ) -> dict[str, object]:
        """Return extracted text for a page range (inclusive, 1-indexed)."""
        tools = _require_tools(ctx)
        return {
            "start_page": start_page,
            "end_page": end_page,
            "text": tools.get_section_text(start_page, end_page),
        }

    def search_text_tool(
        query: str,
        page: int | None = None,
        case_sensitive: bool = False,
        max_results: int = 20,
        ctx: Context[ServerSession, _ServerContext] | None = None,
    ) -> dict[str, object]:
        """Search the latest built text artifact and return page-aware matches."""
        tools = _require_tools(ctx)
        return {
            "query": query,
            "page": page,
            "case_sensitive": case_sensitive,
            "results": tools.search_text(
                query,
                page=page,
                case_sensitive=case_sensitive,
                max_results=max_results,
            ),
        }

    def list_requirements_tool(
        kind: str | None = None,
        prefix: str | None = None,
        max_results: int = 200,
        ctx: Context[ServerSession, _ServerContext] | None = None,
    ) -> dict[str, object]:
        """List requirement IDs from the built AUTOSAR requirement index."""
        tools = _require_tools(ctx)
        return tools.list_requirements(
            kind=kind,
            prefix=prefix,
            max_results=max_results,
        )

    def get_requirement_context_tool(
        requirement_id: str,
        include_text: bool = False,
        max_text_pages: int = 2,
        ctx: Context[ServerSession, _ServerContext] | None = None,
    ) -> dict[str, object]:
        """Return indexed context for one AUTOSAR requirement ID."""
        tools = _require_tools(ctx)
        return tools.get_requirement_context(
            requirement_id,
            include_text=include_text,
            max_text_pages=max_text_pages,
        )

    server.tool(
        name="build_document",
        description=(
            "Build the enriched ToC JSON and page-matched text file for an "
            "AUTOSAR standard document. CALL THIS FIRST with a pdf_source "
            "(local path or URL) "
            "before using any other tool. Calling again with a different "
            "source switches documents (cached if same source). Returns an "
            "artifact manifest with source info, total pages, ToC quality "
            "score, and a compact Table of Contents with section hierarchy, "
            "page ranges, table counts, and requirement counts. Use "
            "get_section_text/search_text/get_requirement_context for "
            "detailed content instead of reading the full JSON.\n\n"
            "IMPORTANT - include_summaries: Leave as False (default) unless "
            "the user explicitly requests summaries. Generating summaries "
            "makes one LLM call per ToC section, which is slow and "
            "expensive. The ToC, text file, and other tools already provide "
            "enough context for most tasks.\n\n"
            "IMPORTANT - model: Do NOT set this unless summaries are "
            "requested or ToC quality is very poor. When needed, use one of "
            "the models available on the LiteLLM gateway: gpt-4.1 "
            "(recommended default), gpt-5-mini, gpt-5-nano, gpt-4.1-nano, "
            "gpt-4o-mini, gpt-5, gpt-5.1, gpt-5.2. Do NOT invent or guess "
            "model names."
        ),
    )(build_document_tool)
    server.tool(
        name="get_section_text",
        description=(
            "Read the extracted text for a page range (inclusive, 1-indexed). "
            "Pass start_page/end_page from ToC nodes to read specific sections. "
            "For a single page use the same value for both. Prefer reading "
            "whole sections rather than page-by-page."
        ),
    )(get_section_text_tool)
    server.tool(
        name="search_text",
        description=(
            "Search the full extracted text for a substring and return "
            "page-aware snippets with surrounding context. Use to locate "
            "requirement IDs, values, or keywords across the entire document "
            "before reading specific sections."
        ),
    )(search_text_tool)
    server.tool(
        name="list_requirements",
        description=(
            "List AUTOSAR requirement IDs from the built requirement index. "
            "Use this instead of reading the full JSON when you need to "
            "discover available SWS/RS/SRS/TPS IDs. Optionally filter by "
            "occurrence kind ('definition', 'reference', 'traceability', "
            "'change_history') or by ID prefix."
        ),
    )(list_requirements_tool)
    server.tool(
        name="get_requirement_context",
        description=(
            "Return the indexed context for one AUTOSAR requirement ID: "
            "occurrence counts, definition/reference pages, specific "
            "sections, and short snippets. Prefer this before "
            "get_section_text when answering a question about a known "
            "requirement ID. Set include_text only when the short snippets "
            "are insufficient."
        ),
    )(get_requirement_context_tool)
    server.tool(
        name="inspect_page",
        description=(
            "Render a PDF page as a PNG image for visual inspection. Use "
            "when extracted text is garbled or insufficient -- tables with "
            "complex layouts, block diagrams, pin-out figures, timing "
            "diagrams. Optionally crop with top/bottom/left/right percentages "
            "(0.0-1.0)."
        ),
    )(inspect_page_tool)

    async def extract_table_markdown_tool(
        page: int,
        ctx: Context[ServerSession, _ServerContext] | None = None,
    ) -> dict[str, object]:
        """Re-extract a single page as layout-aware Markdown."""
        tools = _require_tools(ctx)
        markdown = await asyncio.to_thread(tools.extract_table_markdown, page)
        return {
            "page": page,
            "markdown": markdown,
        }

    server.tool(
        name="extract_table_markdown",
        description=(
            "Re-extract a single page as layout-aware Markdown with proper "
            "table formatting (| delimited rows). Use when get_section_text "
            "shows a garbled or misaligned table and you need clean structured "
            "data for parameter extraction. Cheaper than inspect_page (text "
            "tokens vs vision tokens) but slower (~3s per page). Pass the "
            "1-indexed page number from the PAGE marker."
        ),
    )(extract_table_markdown_tool)
    return server


def _require_tools(ctx: Any) -> AutosarTools:
    if ctx is None:
        raise RuntimeError("MCP context was not provided")
    tools = ctx.request_context.lifespan_context.tools
    if tools is None:
        raise RuntimeError(
            "No document loaded. Call build_document with a pdf_source first."
        )
    return tools


def run_mcp_server(
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
    streamable_http_path: str = "/mcp",
) -> None:
    """Run the local MCP server."""
    server = create_local_mcp_server(
        host=host,
        port=port,
        streamable_http_path=streamable_http_path,
    )
    server.run(transport=transport)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autosarindex-mcp-server",
        description=(
            "Run autosarindex as a local MCP server. "
            "Use build_document to load a PDF source."
        ),
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport to expose (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind for HTTP-based transports",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind for HTTP-based transports",
    )
    parser.add_argument(
        "--streamable-http-path",
        default="/mcp",
        help="Path to expose when using streamable-http transport",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the local MCP server and return an exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        run_mcp_server(
            transport=args.transport,
            host=args.host,
            port=args.port,
            streamable_http_path=args.streamable_http_path,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def main_cli() -> None:
    """Entry point for console_scripts."""
    raise SystemExit(main())


if __name__ == "__main__":
    main_cli()
