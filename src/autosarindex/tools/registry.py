"""Tool registration for Agent SDK / MCP."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from autosarindex.core.textfile import TextSearchMatch, extract_section_text
from autosarindex.core.textfile import search_text as search_text_content
from autosarindex.index import AutosarIndex
from autosarindex.llm.client import close_llm_client
from autosarindex.models import AutosarArtifacts
from autosarindex.tools.vision import Detail, inspect_page

if TYPE_CHECKING:
    import pymupdf


@dataclass(frozen=True)
class _BuildOptions:
    output_dir: str
    output_stem: str | None
    include_summaries: bool
    model: str | None


class AutosarTools:
    """Wraps indexing tools with a bound PDF document."""

    def __init__(self, pdf_path: str) -> None:
        self.pdf_path = pdf_path
        self._index = AutosarIndex(pdf_path)
        self._artifacts: AutosarArtifacts | None = None
        self._build_options: _BuildOptions | None = None

    def __enter__(self) -> AutosarTools:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        self.close()

    @property
    def doc(self) -> pymupdf.Document:
        """Lazy-open the PDF document."""
        return self._index.doc

    @property
    def _doc(self) -> pymupdf.Document | None:
        """Expose current bound document state for compatibility/tests."""
        return self._index._doc

    def close(self) -> None:
        """Close the underlying PDF document."""
        self._index.close()
        self._artifacts = None
        self._build_options = None

    def inspect_page(
        self,
        page: int,
        region: dict[str, float] | None = None,
        dpi: int | None = None,
        detail: Detail = "medium",
    ) -> list[dict]:
        """Render a PDF page as an image for visual inspection.

        Delegates to ``autosarindex.tools.vision.inspect_page`` with the
        bound document. Defaults to ``detail="medium"`` (100 dpi, ~1150
        vision tokens per page on the Anthropic ``(W*H)/750`` formula)
        because this is the agent-surface wrapper: most loop calls don't
        need 150-dpi footnote fidelity. See ``vision.inspect_page`` for
        the full tier semantics.
        """
        return inspect_page(self.doc, page, region=region, dpi=dpi, detail=detail)

    def extract_table_markdown(self, page: int) -> str:
        """Extract a single page as layout-aware markdown with table structure.

        Requires the ``[layout]`` extra (``pymupdf4llm``). Returns markdown
        with proper table formatting using ``|`` delimiters.
        """
        total = len(self.doc)
        if page < 1 or page > total:
            raise ValueError(f"page must be between 1 and {total}")
        try:
            import pymupdf4llm
        except ImportError:
            raise ImportError(
                "pymupdf4llm is required for table markdown extraction. "
                "Install it with: uv sync --extra layout"
            ) from None
        return pymupdf4llm.to_markdown(self.doc, pages=[page - 1], show_progress=False)

    def build_document(
        self,
        output_dir: str | None = None,
        output_stem: str | None = None,
        include_summaries: bool = False,
        model: str | None = None,
        force_rebuild: bool = False,
    ) -> AutosarArtifacts:
        """Build and cache document artifacts for later MCP queries."""
        if include_summaries and model is None:
            raise ValueError("--include-summaries requires --model")

        # Resolve once so the cache key is the actual destination path -- two
        # successive calls with output_dir=None must miss the cache if the
        # resolver default has changed between them (e.g. env var rebound).
        from autosarindex.index import resolve_default_output_dir

        resolved_output_dir = (
            output_dir
            if output_dir is not None and output_dir.strip()
            else resolve_default_output_dir()
        )

        options = _BuildOptions(
            output_dir=resolved_output_dir,
            output_stem=output_stem,
            include_summaries=include_summaries,
            model=model,
        )
        if (
            not force_rebuild
            and self._artifacts is not None
            and self._build_options == options
            and self._artifacts.json_path is not None
            and self._artifacts.json_path.exists()
            and self._artifacts.text_path is not None
            and self._artifacts.text_path.exists()
        ):
            return self._artifacts

        llm_callable = None
        try:
            if model is not None:
                from autosarindex.llm.client import create_llm_client

                llm_callable = create_llm_client(model=model)

            artifacts = self._index.build(
                output_dir=resolved_output_dir,
                output_stem=output_stem,
                include_summaries=include_summaries,
                llm_callable=llm_callable,
            )
        finally:
            close_llm_client(llm_callable)

        self._artifacts = artifacts
        self._build_options = options
        return artifacts

    def build_datasheet(
        self,
        output_dir: str | None = None,
        output_stem: str | None = None,
        include_summaries: bool = False,
        model: str | None = None,
        force_rebuild: bool = False,
    ) -> AutosarArtifacts:
        """Compatibility alias for older callers."""
        return self.build_document(
            output_dir=output_dir,
            output_stem=output_stem,
            include_summaries=include_summaries,
            model=model,
            force_rebuild=force_rebuild,
        )

    def get_artifact_manifest(self) -> dict[str, object]:
        """Return a compact summary of the currently built artifacts."""
        artifacts = self._require_artifacts()
        return {
            "source": artifacts.json_data.get("source"),
            "document_type": artifacts.json_data.get("document_type"),
            "total_pages": self._total_pages(artifacts),
            "json_path": (
                str(artifacts.json_path) if artifacts.json_path is not None else None
            ),
            "text_path": (
                str(artifacts.text_path) if artifacts.text_path is not None else None
            ),
            "toc_quality": artifacts.json_data.get("toc_quality"),
            "autosar_metadata": artifacts.json_data.get("autosar_metadata"),
            "autosar_requirements": self._autosar_requirement_manifest(artifacts),
            "toc": self._compact_toc_nodes(artifacts.json_data.get("toc")),
        }

    def list_requirements(
        self,
        *,
        kind: str | None = None,
        prefix: str | None = None,
        max_results: int = 200,
    ) -> dict[str, object]:
        """List requirement IDs from the built AUTOSAR index."""
        requirements = self._autosar_requirements()
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        ids: list[str]
        if kind:
            ids_by_kind = requirements.get("ids_by_kind", {})
            if not isinstance(ids_by_kind, dict):
                ids_by_kind = {}
            values = ids_by_kind.get(kind, [])
            ids = _string_list(values)
        else:
            values = requirements.get("ids", [])
            ids = _string_list(values)

        if prefix:
            ids = [item for item in ids if item.startswith(prefix)]

        return {
            "kind": kind,
            "prefix": prefix,
            "total_matches": len(ids),
            "truncated": len(ids) > max_results,
            "ids": ids[:max_results],
        }

    def get_requirement_context(
        self,
        requirement_id: str,
        *,
        include_text: bool = False,
        max_text_pages: int = 2,
    ) -> dict[str, object]:
        """Return indexed occurrence context for one AUTOSAR requirement ID."""
        requirements = self._autosar_requirements()
        index = requirements.get("index", {})
        if not isinstance(index, dict) or requirement_id not in index:
            raise ValueError(f"Requirement ID not found: {requirement_id}")

        entry = dict(index[requirement_id])
        if include_text:
            if max_text_pages < 1:
                raise ValueError("max_text_pages must be at least 1")
            pages = entry.get("definition_pages") or entry.get("pages") or []
            page_texts = []
            for page in list(pages)[:max_text_pages]:
                page_texts.append(
                    {
                        "page": page,
                        "text": self.get_section_text(int(page), int(page)),
                    }
                )
            entry["page_texts"] = page_texts
            entry["page_texts_truncated"] = len(pages) > max_text_pages
        return entry

    def get_section_text(self, start_page: int, end_page: int) -> str:
        """Return extracted text for a page range from the latest build.

        Returns text WITH ``--- PAGE N ---`` markers so the agent can orient.
        """
        artifacts = self._require_artifacts()
        total_pages = self._total_pages(artifacts)
        if start_page < 1 or end_page > total_pages or start_page > end_page:
            raise ValueError(
                f"start_page/end_page must satisfy "
                f"1 <= start_page <= end_page <= {total_pages}"
            )
        return extract_section_text(artifacts.text_content, start_page, end_page)

    def search_text(
        self,
        query: str,
        *,
        page: int | None = None,
        case_sensitive: bool = False,
        max_results: int = 20,
    ) -> list[TextSearchMatch]:
        """Search the built page-matched text and return page-aware snippets."""
        artifacts = self._require_artifacts()
        total_pages = self._total_pages(artifacts)
        if page is not None and (page < 1 or page > total_pages):
            raise ValueError(f"page must be between 1 and {total_pages}")
        return search_text_content(
            artifacts.text_content,
            query,
            page=page,
            case_sensitive=case_sensitive,
            max_results=max_results,
        )

    def _require_artifacts(self) -> AutosarArtifacts:
        if self._artifacts is None:
            raise RuntimeError(
                "No document artifacts available. Call build_document first."
            )
        return self._artifacts

    def _total_pages(self, artifacts: AutosarArtifacts) -> int:
        total_pages = artifacts.json_data.get("total_pages")
        if not isinstance(total_pages, int):
            raise RuntimeError("Built artifacts are missing total_pages")
        return total_pages

    def _autosar_requirements(self) -> dict:
        artifacts = self._require_artifacts()
        requirements = artifacts.json_data.get("autosar_requirements")
        if not isinstance(requirements, dict):
            raise RuntimeError("Built artifacts do not contain AUTOSAR requirements")
        return requirements

    def _autosar_requirement_manifest(
        self, artifacts: AutosarArtifacts
    ) -> dict[str, object] | None:
        requirements = artifacts.json_data.get("autosar_requirements")
        if not isinstance(requirements, dict):
            return None
        ids_by_kind = requirements.get("ids_by_kind", {})
        ids_by_kind_counts = (
            {
                key: len(value)
                for key, value in ids_by_kind.items()
                if isinstance(value, list)
            }
            if isinstance(ids_by_kind, dict)
            else {}
        )
        return {
            "total_count": requirements.get("total_count"),
            "occurrence_count": requirements.get("occurrence_count"),
            "occurrence_summary": requirements.get("occurrence_summary"),
            "ids_by_kind_counts": ids_by_kind_counts,
            "occurrences_truncated": requirements.get("occurrences_truncated"),
            "lookup": (
                "Use list_requirements for IDs and get_requirement_context "
                "for one requirement's occurrences/pages/snippets."
            ),
        }

    def _compact_toc_nodes(self, nodes: object) -> list[dict[str, object]]:
        if not isinstance(nodes, list):
            return []
        compact: list[dict[str, object]] = []
        for raw_node in nodes:
            if not isinstance(raw_node, dict):
                continue
            raw_node = cast("dict[str, object]", raw_node)
            node = {
                "node_id": raw_node.get("node_id"),
                "title": raw_node.get("title"),
                "level": raw_node.get("level"),
                "start_page": raw_node.get("start_page"),
                "end_page": raw_node.get("end_page"),
            }
            for key in (
                "breadcrumb",
                "autosar_section_type",
                "requirement_count",
                "requirement_occurrence_count",
                "requirement_occurrence_summary",
                "table_count",
            ):
                if key in raw_node:
                    node[key] = raw_node[key]
            child_nodes = self._compact_toc_nodes(raw_node.get("nodes"))
            if child_nodes:
                node["nodes"] = child_nodes
            compact.append(node)
        return compact


def create_autosar_tools_server():
    """Create the MCP/tool server that a consuming agent can mount.

    Requires ``claude-agent-sdk`` to be installed. Raises ``ImportError``
    if the SDK is not available. The server starts without a bound PDF;
    call ``build_document`` with a ``pdf_source`` to load a document.
    """
    import asyncio
    import json
    from typing import Any

    try:
        from claude_agent_sdk import (  # type: ignore[import-not-found]  # ty: ignore[unresolved-import]
            create_sdk_mcp_server,
            tool,
        )
    except ImportError:
        raise ImportError(
            "claude-agent-sdk is required for tool server creation. "
            "Install it with: uv pip install claude-agent-sdk"
        ) from None

    tools_instance: AutosarTools | None = None

    def _ok(result: object) -> dict[str, Any]:
        return {
            "content": [{"type": "text", "text": json.dumps(result, default=str)}],
            "is_error": False,
        }

    def _err(msg: str) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": msg}], "is_error": True}

    def _require() -> AutosarTools:
        if tools_instance is None:
            raise RuntimeError(
                "No document loaded. Call build_document with a pdf_source first."
            )
        return tools_instance

    @tool(
        "build_document",
        "Build the enriched ToC JSON and page-matched text file for an "
        "AUTOSAR standard document. CALL THIS FIRST with a pdf_source "
        "(local path or URL) "
        "before using any other tool. Calling again with a different source "
        "switches documents. Returns an artifact manifest with source info, "
        "total pages, ToC quality score, and a compact Table of Contents with "
        "section hierarchy, page ranges, table counts, and requirement counts. "
        "Use get_section_text/search_text/get_requirement_context for detailed "
        "content instead of reading the full JSON.\n\n"
        "output_dir is optional -- omit it unless you need artifacts at a "
        "specific path; the library picks a writable default.\n\n"
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
        "model names.",
        {
            "type": "object",
            "properties": {
                "pdf_source": {"type": "string"},
                "output_dir": {"type": "string"},
                "output_stem": {"type": "string"},
                "include_summaries": {"type": "boolean"},
                "model": {"type": "string"},
                "force_rebuild": {"type": "boolean"},
            },
            "required": ["pdf_source"],
        },
    )
    async def build_document(args: dict[str, Any]) -> dict[str, Any]:
        nonlocal tools_instance
        try:
            pdf_source = args.get("pdf_source", "")
            if not pdf_source:
                return _err("pdf_source is required")
            # Re-bind if source changed
            if tools_instance is None or tools_instance.pdf_path != pdf_source:
                if tools_instance is not None:
                    tools_instance.close()
                tools_instance = AutosarTools(pdf_source)
            await asyncio.to_thread(
                tools_instance.build_document,
                output_dir=args.get("output_dir"),
                output_stem=args.get("output_stem"),
                include_summaries=args.get("include_summaries", False),
                model=args.get("model"),
                force_rebuild=args.get("force_rebuild", False),
            )
            return _ok(tools_instance.get_artifact_manifest())
        except Exception as exc:
            return _err(str(exc))

    @tool(
        "get_section_text",
        "Read the extracted text for a page range (inclusive, 1-indexed). "
        "Pass start_page/end_page from ToC nodes to read specific sections. "
        "For a single page use the same value for both. Prefer reading whole "
        "sections rather than page-by-page.",
        {
            "type": "object",
            "properties": {
                "start_page": {"type": "integer", "minimum": 1},
                "end_page": {"type": "integer", "minimum": 1},
            },
            "required": ["start_page", "end_page"],
        },
    )
    async def get_section_text(args: dict[str, Any]) -> dict[str, Any]:
        try:
            ti = _require()
            text = ti.get_section_text(args["start_page"], args["end_page"])
            result = {
                "start_page": args["start_page"],
                "end_page": args["end_page"],
                "text": text,
            }
            return _ok(result)
        except Exception as exc:
            return _err(str(exc))

    @tool(
        "search_text",
        "Search the full extracted text for a substring and return page-aware "
        "snippets with surrounding context. Use to locate parameters, values, "
        "or keywords across the entire document before reading specific sections. "
        "Omit 'page' to search all pages.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "page": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "1-indexed page to search. Omit to search all.",
                },
                "case_sensitive": {"type": "boolean"},
                "max_results": {"type": "integer"},
            },
            "required": ["query"],
        },
    )
    async def search_text(args: dict[str, Any]) -> dict[str, Any]:
        try:
            results = _require().search_text(
                args["query"],
                page=args.get("page"),
                case_sensitive=args.get("case_sensitive", False),
                max_results=args.get("max_results", 20),
            )
            return _ok({"query": args["query"], "results": results})
        except Exception as exc:
            return _err(str(exc))

    @tool(
        "list_requirements",
        "List AUTOSAR requirement IDs from the built requirement index. Use "
        "this instead of reading the full JSON when you need to discover "
        "available SWS/RS/SRS/TPS IDs. Optionally filter by occurrence kind "
        "('definition', 'reference', 'traceability', 'change_history') or by "
        "ID prefix.",
        {
            "type": "object",
            "properties": {
                "kind": {"type": "string"},
                "prefix": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1},
            },
        },
    )
    async def list_requirements(args: dict[str, Any]) -> dict[str, Any]:
        try:
            return _ok(
                _require().list_requirements(
                    kind=args.get("kind"),
                    prefix=args.get("prefix"),
                    max_results=args.get("max_results", 200),
                )
            )
        except Exception as exc:
            return _err(str(exc))

    @tool(
        "get_requirement_context",
        "Return the indexed context for one AUTOSAR requirement ID: occurrence "
        "counts, definition/reference pages, specific sections, and short "
        "snippets. Prefer this before get_section_text when answering a "
        "question about a known requirement ID. Set include_text only when the "
        "short snippets are insufficient.",
        {
            "type": "object",
            "properties": {
                "requirement_id": {"type": "string"},
                "include_text": {"type": "boolean"},
                "max_text_pages": {"type": "integer", "minimum": 1},
            },
            "required": ["requirement_id"],
        },
    )
    async def get_requirement_context(args: dict[str, Any]) -> dict[str, Any]:
        try:
            return _ok(
                _require().get_requirement_context(
                    args["requirement_id"],
                    include_text=args.get("include_text", False),
                    max_text_pages=args.get("max_text_pages", 2),
                )
            )
        except Exception as exc:
            return _err(str(exc))

    @tool(
        "inspect_page",
        "Render a PDF page as a PNG image for visual inspection. Use when "
        "extracted text is garbled or insufficient -- tables with complex "
        "layouts, block diagrams, pin-out figures, timing diagrams. Optionally "
        "crop with top/bottom/left/right percentages (0.0-1.0). Pick `detail` "
        "to control vision-token cost: 'low' for layout overview, 'medium' "
        "(recommended default) for body text and table cells, 'high' for "
        "footnotes / subscripts / dense schematics.",
        {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "minimum": 1},
                "region": {
                    "type": "object",
                    "description": "Crop region with top/bottom/left/right (0.0-1.0)",
                },
                "detail": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": (
                        "Vision-token-cost tier. low=75 dpi, "
                        "medium=100 dpi (recommended), high=150 dpi."
                    ),
                },
                "dpi": {
                    "type": "integer",
                    "description": "Explicit override; wins over `detail`.",
                },
            },
            "required": ["page"],
        },
    )
    async def inspect_page(args: dict[str, Any]) -> dict[str, Any]:
        try:
            blocks = _require().inspect_page(
                args["page"],
                region=args.get("region"),
                dpi=args.get("dpi"),
                detail=args.get("detail", "medium"),
            )
            return {
                "content": [
                    {
                        "type": "image",
                        "data": blocks[0]["data"],
                        "mime_type": blocks[0]["mime_type"],
                    }
                ],
                "is_error": False,
            }
        except Exception as exc:
            return _err(str(exc))

    @tool(
        "extract_table_markdown",
        "Re-extract a single page as layout-aware Markdown with proper table "
        "formatting. Use when get_section_text shows a garbled or misaligned "
        "table and you need clean | delimited rows for parameter extraction. "
        "Cheaper than inspect_page (text tokens vs vision tokens) but slower "
        "(~3s per page). Pass the 1-indexed page number from the PAGE marker.",
        {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "minimum": 1},
            },
            "required": ["page"],
        },
    )
    async def extract_table_markdown(args: dict[str, Any]) -> dict[str, Any]:
        try:
            md = await asyncio.to_thread(
                _require().extract_table_markdown, args["page"]
            )
            return _ok({"page": args["page"], "markdown": md})
        except ImportError as exc:
            return _err(str(exc))
        except Exception as exc:
            return _err(str(exc))

    return create_sdk_mcp_server(
        name="autosarindex",
        version="1.0.0",
        tools=[
            build_document,
            get_section_text,
            search_text,
            list_requirements,
            get_requirement_context,
            inspect_page,
            extract_table_markdown,
        ],
    )


create_document_tools_server = create_autosar_tools_server
create_datasheet_tools_server = create_autosar_tools_server
DatasheetTools = AutosarTools


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]
