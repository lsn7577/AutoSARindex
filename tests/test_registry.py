"""Tests for tool registry."""

import sys
import types
from pathlib import Path
from typing import cast

import pymupdf
import pytest

from autosarindex.tools.registry import (
    AutosarTools,
    create_autosar_tools_server,
)

DATA2PAGE_DIR = Path(__file__).resolve().parent.parent.parent / "data2page"
TLE9350_PATH = DATA2PAGE_DIR / "Infineon-TLE9350BSJ-DataSheet-v01_00-EN.pdf"


def test_datasheet_tools_inspect_page(tmp_path):
    """AutosarTools.inspect_page should work with a valid PDF."""
    # Create a minimal test PDF
    pdf_path = tmp_path / "test.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    writer = pymupdf.TextWriter(page.rect)
    writer.append((72, 72), "Registry test")
    writer.write_text(page)
    doc.save(str(pdf_path))
    doc.close()

    tools = AutosarTools(str(pdf_path))
    result = tools.inspect_page(page=1)
    tools.close()

    assert len(result) == 1
    assert result[0]["type"] == "image"


def test_datasheet_tools_build_and_query_artifacts(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    writer = pymupdf.TextWriter(page.rect)
    writer.append((72, 72), "Supply voltage 4.5V to 5.5V")
    writer.write_text(page)
    doc.save(str(pdf_path))
    doc.close()

    output_dir = tmp_path / "out"
    tools = AutosarTools(str(pdf_path))
    artifacts = tools.build_document(output_dir=str(output_dir))

    section_text = tools.get_section_text(1, 1)
    matches = tools.search_text("5.5v")
    tools.close()

    assert artifacts.json_path is not None
    assert artifacts.text_path is not None
    assert "--- PAGE 1 ---" in section_text
    assert "Supply voltage" in section_text
    assert matches == [
        {
            "page": 1,
            "start": 23,
            "end": 27,
            "snippet": "Supply voltage 4.5V to 5.5V",
        }
    ]


def test_autosar_tools_build_document_alias(tmp_path):
    from autosarindex import AutosarTools

    pdf_path = tmp_path / "autosar.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    writer = pymupdf.TextWriter(page.rect)
    writer.append((72, 72), "AUTOSAR Specification of Test AUTOSAR_SWS_TEST")
    writer.append((72, 92), "[SWS_Test_00001] The module shall start.")
    writer.append((72, 112), "Figure 1.1: Module startup flow")
    writer.append((72, 132), "Init Run Stop")
    writer.write_text(page)
    doc.save(str(pdf_path))
    doc.close()

    tools = AutosarTools(str(pdf_path))
    try:
        artifacts = tools.build_document(output_dir=str(tmp_path / "out"))
        manifest = tools.get_artifact_manifest()
        listed = tools.list_requirements()
        context = tools.get_requirement_context("SWS_Test_00001")
        figure_matches = tools.search_figures("startup")
        figure_context = tools.get_figure_context("Figure 1.1")
    finally:
        tools.close()

    assert artifacts.json_data["document_type"] == "autosar"
    assert artifacts.json_data["autosar_requirements"]["ids"] == ["SWS_Test_00001"]
    manifest_requirements = manifest["autosar_requirements"]
    assert isinstance(manifest_requirements, dict)
    manifest_requirements = cast("dict[str, object]", manifest_requirements)
    assert "ids" not in manifest_requirements
    assert manifest_requirements["ids_by_kind_counts"] == {"definition": 1}
    manifest_toc = manifest["toc"]
    assert isinstance(manifest_toc, list)
    manifest_visual_index = manifest["visual_index"]
    assert isinstance(manifest_visual_index, dict)
    manifest_visual_index = cast("dict[str, object]", manifest_visual_index)
    assert manifest_visual_index["figure_count"] == 1
    assert listed["ids"] == ["SWS_Test_00001"]
    assert context["definition_pages"] == [1]
    occurrences = context["occurrences"]
    assert isinstance(occurrences, list)
    first_occurrence = occurrences[0]
    assert isinstance(first_occurrence, dict)
    first_occurrence = cast("dict[str, object]", first_occurrence)
    snippet = first_occurrence["snippet"]
    assert isinstance(snippet, str)
    assert "[SWS_Test_00001]" in snippet
    assert figure_matches["total_matches"] == 1
    assert figure_context["page"] == 1
    inspect_hint = figure_context["inspect_hint"]
    assert isinstance(inspect_hint, dict)
    inspect_hint = cast("dict[str, object]", inspect_hint)
    assert inspect_hint["page"] == 1


def test_build_document_omitted_output_dir_uses_resolver(monkeypatch, tmp_path):
    """AutosarTools.build_document(output_dir=None) writes to resolver default."""
    pdf_path = tmp_path / "test.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    writer = pymupdf.TextWriter(page.rect)
    writer.append((72, 72), "Hello")
    writer.write_text(page)
    doc.save(str(pdf_path))
    doc.close()

    pinned = tmp_path / "env-pinned"
    monkeypatch.setenv("DATASHEETINDEX_OUTPUT_DIR", str(pinned))

    tools = AutosarTools(str(pdf_path))
    try:
        artifacts = tools.build_document()
    finally:
        tools.close()

    assert artifacts.json_path is not None
    assert artifacts.json_path.parent == pinned


def test_build_document_cache_invalidated_when_resolver_changes(monkeypatch, tmp_path):
    """Cache must miss if env var (and thus resolver default) changed between calls."""
    pdf_path = tmp_path / "test.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    writer = pymupdf.TextWriter(page.rect)
    writer.append((72, 72), "Hello")
    writer.write_text(page)
    doc.save(str(pdf_path))
    doc.close()

    first = tmp_path / "first"
    second = tmp_path / "second"

    tools = AutosarTools(str(pdf_path))
    try:
        monkeypatch.setenv("DATASHEETINDEX_OUTPUT_DIR", str(first))
        a1 = tools.build_document()
        monkeypatch.setenv("DATASHEETINDEX_OUTPUT_DIR", str(second))
        a2 = tools.build_document()
    finally:
        tools.close()

    assert a1.json_path is not None and a1.json_path.parent == first
    assert a2.json_path is not None and a2.json_path.parent == second


def test_datasheet_tools_artifact_queries_require_build(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(pdf_path))
    doc.close()

    tools = AutosarTools(str(pdf_path))
    with pytest.raises(RuntimeError, match="build_document"):
        tools.get_section_text(1, 1)
    with pytest.raises(RuntimeError, match="build_document"):
        tools.search_text("foo")
    tools.close()


def test_datasheet_tools_lazy_doc(tmp_path):
    """Document should be lazy-opened."""
    pdf_path = tmp_path / "test.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(pdf_path))
    doc.close()

    tools = AutosarTools(str(pdf_path))
    assert tools._doc is None
    _ = tools.doc
    assert tools._doc is not None
    tools.close()
    assert tools._doc is None


def test_create_server_raises_without_sdk():
    """create_autosar_tools_server should raise ImportError without SDK."""
    with pytest.raises(ImportError, match="claude-agent-sdk"):
        create_autosar_tools_server()


def test_create_server_registers_tools(monkeypatch, tmp_path):
    """Server factory should register agent-ready tools via SDK pattern."""
    import asyncio

    pdf_path = tmp_path / "test.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    writer = pymupdf.TextWriter(page.rect)
    writer.append((72, 72), "Registry MCP test")
    writer.write_text(page)
    doc.save(str(pdf_path))
    doc.close()

    def fake_tool(name, description, params):
        def decorator(func):
            func._tool_name = name
            return func

        return decorator

    def fake_create_sdk_mcp_server(name, version, tools):
        return types.SimpleNamespace(
            name=name,
            version=version,
            tools={t._tool_name: t for t in tools},
        )

    monkeypatch.setitem(
        sys.modules,
        "claude_agent_sdk",
        types.SimpleNamespace(
            tool=fake_tool,
            create_sdk_mcp_server=fake_create_sdk_mcp_server,
        ),
    )

    server = create_autosar_tools_server()

    assert set(server.tools) == {
        "build_document",
        "get_section_text",
        "search_text",
        "list_requirements",
        "get_requirement_context",
        "search_figures",
        "get_figure_context",
        "inspect_page",
        "extract_table_markdown",
    }

    build_result = asyncio.run(
        server.tools["build_document"](
            {"pdf_source": str(pdf_path), "output_dir": str(tmp_path / "out")}
        )
    )
    assert build_result["is_error"] is False

    section_result = asyncio.run(
        server.tools["get_section_text"]({"start_page": 1, "end_page": 1})
    )
    assert section_result["is_error"] is False

    search_result = asyncio.run(server.tools["search_text"]({"query": "registry"}))
    assert search_result["is_error"] is False

    inspect_result = asyncio.run(server.tools["inspect_page"]({"page": 1}))
    assert inspect_result["is_error"] is False

    # extract_table_markdown requires pymupdf4llm; verify graceful error
    table_md_result = asyncio.run(server.tools["extract_table_markdown"]({"page": 1}))
    # Will be is_error=True if pymupdf4llm not installed, False if it is
    assert isinstance(table_md_result["is_error"], bool)


def test_mcp_build_document_omits_output_dir(monkeypatch, tmp_path):
    """When the MCP caller omits output_dir, the library default is used."""
    import asyncio

    pdf_path = tmp_path / "test.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    writer = pymupdf.TextWriter(page.rect)
    writer.append((72, 72), "Default output_dir test")
    writer.write_text(page)
    doc.save(str(pdf_path))
    doc.close()

    def fake_tool(name, description, params):
        def decorator(func):
            func._tool_name = name
            return func

        return decorator

    def fake_create_sdk_mcp_server(name, version, tools):
        return types.SimpleNamespace(
            name=name, version=version, tools={t._tool_name: t for t in tools}
        )

    monkeypatch.setitem(
        sys.modules,
        "claude_agent_sdk",
        types.SimpleNamespace(
            tool=fake_tool, create_sdk_mcp_server=fake_create_sdk_mcp_server
        ),
    )
    # Pin the resolver so the test stays hermetic
    pinned = tmp_path / "resolved-out"
    monkeypatch.setenv("DATASHEETINDEX_OUTPUT_DIR", str(pinned))

    server = create_autosar_tools_server()
    result = asyncio.run(server.tools["build_document"]({"pdf_source": str(pdf_path)}))
    assert result["is_error"] is False
    assert pinned.exists() and any(pinned.iterdir())


@pytest.mark.real_pdf
def test_real_pdf_tools():
    """AutosarTools should work with the real test PDF."""
    if not TLE9350_PATH.exists():
        pytest.skip("Test PDF not found")

    tools = AutosarTools(str(TLE9350_PATH))
    result = tools.inspect_page(page=1)
    tools.close()

    assert result[0]["type"] == "image"
    assert len(result[0]["data"]) > 0


def test_datasheet_tools_supports_url_source(monkeypatch):
    from tests.conftest import DummyDoc, FakeResponse

    opened_paths: list[str] = []

    def fake_urlopen(url: str, timeout: int):
        assert url == "https://example.com/test.pdf"
        assert timeout > 0
        return FakeResponse(b"%PDF-1.7\nmock")

    def fake_open(path: str):
        opened_paths.append(path)
        return DummyDoc()

    monkeypatch.setattr("autosarindex.index.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("autosarindex.index.pymupdf.open", fake_open)

    tools = AutosarTools("https://example.com/test.pdf")
    _ = tools.doc
    assert len(opened_paths) == 1
    temp_path = Path(opened_paths[0])
    assert temp_path.exists()

    tools.close()
    assert tools._doc is None
    assert not temp_path.exists()
