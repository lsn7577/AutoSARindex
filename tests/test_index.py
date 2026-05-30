"""Tests for the main AutosarIndex orchestrator."""

import json
import re
import urllib.error
from pathlib import Path

import pytest

from autosarindex.index import AutosarIndex
from autosarindex.models import TocNode, TocQuality

DATA2PAGE_DIR = Path(__file__).resolve().parent.parent.parent / "data2page"
TLE9350_PATH = DATA2PAGE_DIR / "Infineon-TLE9350BSJ-DataSheet-v01_00-EN.pdf"


@pytest.mark.real_pdf
def test_build_produces_artifacts(tmp_path):
    """Full pipeline should produce valid artifacts."""
    if not TLE9350_PATH.exists():
        pytest.skip("Test PDF not found")

    idx = AutosarIndex(str(TLE9350_PATH))
    artifacts = idx.build(output_dir=str(tmp_path))
    idx.close()

    # Files exist on disk
    assert artifacts.json_path is not None
    assert artifacts.text_path is not None
    assert artifacts.json_path.exists()
    assert artifacts.text_path.exists()


@pytest.mark.real_pdf
def test_json_structure(tmp_path):
    """JSON output should have the expected top-level keys."""
    if not TLE9350_PATH.exists():
        pytest.skip("Test PDF not found")

    idx = AutosarIndex(str(TLE9350_PATH))
    artifacts = idx.build(output_dir=str(tmp_path))
    idx.close()

    data = artifacts.json_data
    assert "source" in data
    assert "total_pages" in data
    assert "preamble" in data
    assert "toc_quality" in data
    assert "toc" in data
    assert isinstance(data["toc"], list)
    assert data["total_pages"] > 0


@pytest.mark.real_pdf
def test_json_file_valid(tmp_path):
    """The JSON file on disk should be valid JSON."""
    if not TLE9350_PATH.exists():
        pytest.skip("Test PDF not found")

    idx = AutosarIndex(str(TLE9350_PATH))
    artifacts = idx.build(output_dir=str(tmp_path))
    idx.close()

    assert artifacts.json_path is not None
    content = artifacts.json_path.read_text(encoding="utf-8")
    parsed = json.loads(content)
    assert parsed["source"] == "Infineon-TLE9350BSJ-DataSheet-v01_00-EN.pdf"


@pytest.mark.real_pdf
def test_text_file_page_alignment(tmp_path):
    """Page count in text file should match total_pages in JSON."""
    if not TLE9350_PATH.exists():
        pytest.skip("Test PDF not found")

    idx = AutosarIndex(str(TLE9350_PATH))
    artifacts = idx.build(output_dir=str(tmp_path))
    idx.close()

    total_pages = artifacts.json_data["total_pages"]
    markers = re.findall(r"--- PAGE (\d+) ---", artifacts.text_content)
    assert len(markers) == total_pages

    # Verify sequential numbering 1..N
    numbers = [int(m) for m in markers]
    assert numbers == list(range(1, total_pages + 1))


@pytest.mark.real_pdf
def test_toc_quality_populated(tmp_path):
    """Quality assessment should be populated."""
    if not TLE9350_PATH.exists():
        pytest.skip("Test PDF not found")

    idx = AutosarIndex(str(TLE9350_PATH))
    artifacts = idx.build(output_dir=str(tmp_path))
    idx.close()

    assert artifacts.toc_quality is not None
    assert artifacts.toc_quality.score > 0
    assert artifacts.toc_quality.entry_count > 0


@pytest.mark.real_pdf
def test_lazy_doc_and_close():
    """Doc property should lazy-open; close should release."""
    if not TLE9350_PATH.exists():
        pytest.skip("Test PDF not found")

    idx = AutosarIndex(str(TLE9350_PATH))
    assert idx._doc is None
    _ = idx.doc
    assert idx._doc is not None
    idx.close()
    assert idx._doc is None


def test_url_source_downloads_and_cleans_up(monkeypatch):
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

    idx = AutosarIndex("https://example.com/test.pdf")
    _ = idx.doc
    assert len(opened_paths) == 1
    assert idx._temp_pdf_path is not None
    assert idx._temp_pdf_path.exists()
    assert idx._source_file_name() == "test.pdf"
    idx.close()
    assert idx._temp_pdf_path is None


def test_url_source_rejects_non_pdf_content_type(monkeypatch):
    from tests.conftest import FakeResponse

    def fake_urlopen(url: str, timeout: int):
        return FakeResponse(b"<!doctype html>", content_type="text/html")

    monkeypatch.setattr("autosarindex.index.urllib.request.urlopen", fake_urlopen)

    idx = AutosarIndex("https://example.com/test.pdf")
    with pytest.raises(ValueError, match="did not return a PDF content type"):
        _ = idx.doc


def test_url_source_rejects_non_pdf_body(monkeypatch):
    from tests.conftest import FakeResponse

    def fake_urlopen(url: str, timeout: int):
        return FakeResponse(b"<!doctype html>", content_type="application/pdf")

    monkeypatch.setattr("autosarindex.index.urllib.request.urlopen", fake_urlopen)

    idx = AutosarIndex("https://example.com/test.pdf")
    with pytest.raises(ValueError, match="not a valid PDF"):
        _ = idx.doc


def test_url_source_retries_on_ssl_error(monkeypatch):
    """SSL certificate errors should trigger a retry without verification."""
    import ssl

    from tests.conftest import DummyDoc, FakeResponse

    call_count = 0

    def fake_urlopen(url, timeout=None, context=None):
        nonlocal call_count
        call_count += 1
        if context is None:
            # First attempt 鈥?simulate SSL failure
            raise urllib.error.URLError(
                ssl.SSLCertVerificationError(
                    "certificate verify failed: self-signed certificate"
                )
            )
        # Retry with unverified context
        assert context.check_hostname is False
        return FakeResponse(b"%PDF-1.7\nmock")

    opened_paths: list[str] = []

    def fake_open(path: str):
        opened_paths.append(path)
        return DummyDoc()

    monkeypatch.setattr("autosarindex.index.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("autosarindex.index.pymupdf.open", fake_open)

    idx = AutosarIndex("https://vendor.example.com/datasheet.pdf")
    _ = idx.doc
    assert call_count == 2
    assert len(opened_paths) == 1
    idx.close()


class _FakeBuildDoc:
    def __init__(self, pages: int = 3):
        self._pages = pages
        self.closed = False

    def __len__(self):
        return self._pages

    def close(self):
        self.closed = True


def test_build_auto_llm_fallback_when_quality_low(monkeypatch, tmp_path):
    quality_calls = [0]
    fallback_calls: list[object] = []
    llm_models: list[str] = []
    fake_llm: object | None = None

    def fake_open(_path: str):
        return _FakeBuildDoc()

    def fake_quality(_nodes, _total_pages):
        quality_calls[0] += 1
        if quality_calls[0] == 1:
            return TocQuality(score=0.0, entry_count=0, max_depth=0, page_coverage=0.0)
        return TocQuality(score=0.8, entry_count=1, max_depth=1, page_coverage=1.0)

    class _FakeAutoLlm:
        def __init__(self) -> None:
            self.closed = False

        def __call__(self, _system: str, _user: str) -> str:
            return "ok"

        def close(self) -> None:
            self.closed = True

    fake_llm = _FakeAutoLlm()

    def fake_client(model: str):
        llm_models.append(model)
        return fake_llm

    def fake_toc_from_text(_text: str, _total_pages: int, llm_callable):
        fallback_calls.append(llm_callable)
        return [
            TocNode(
                title="Auto",
                level=1,
                start_page=1,
                end_page=1,
                node_id="0001",
            )
        ]

    monkeypatch.setattr("autosarindex.index.pymupdf.open", fake_open)
    monkeypatch.setattr(
        "autosarindex.index.generate_text", lambda _doc: "--- PAGE 1 ---\n"
    )
    monkeypatch.setattr("autosarindex.index.generate_preamble", lambda _doc: "pre")
    monkeypatch.setattr("autosarindex.index.extract_toc", lambda _doc: [])
    monkeypatch.setattr("autosarindex.index.build_tree", lambda _raw, _pages: [])
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_table_counts",
        lambda _nodes, _doc, **_kw: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_continued_tables",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_footnote_markers",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_cross_references",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr("autosarindex.index.assess_toc_quality", fake_quality)
    monkeypatch.setattr("autosarindex.llm.client.create_llm_client", fake_client)
    monkeypatch.setattr(
        "autosarindex.llm.toc_fallback.generate_toc_from_text",
        fake_toc_from_text,
    )

    idx = AutosarIndex("dummy.pdf")
    artifacts = idx.build(output_dir=str(tmp_path))
    idx.close()

    assert artifacts.toc_quality is not None
    assert artifacts.toc_quality.score == 0.8
    assert llm_models == ["gpt-4.1"]
    assert len(fallback_calls) == 1
    assert artifacts.json_data["toc"][0]["title"] == "Auto"
    assert fake_llm.closed is True


def test_build_auto_llm_fallback_graceful_without_credentials(monkeypatch, tmp_path):
    def fake_open(_path: str):
        return _FakeBuildDoc()

    monkeypatch.setattr("autosarindex.index.pymupdf.open", fake_open)
    monkeypatch.setattr(
        "autosarindex.index.generate_text", lambda _doc: "--- PAGE 1 ---\n"
    )
    monkeypatch.setattr("autosarindex.index.generate_preamble", lambda _doc: "pre")
    monkeypatch.setattr("autosarindex.index.extract_toc", lambda _doc: [])
    monkeypatch.setattr("autosarindex.index.build_tree", lambda _raw, _pages: [])
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_table_counts",
        lambda _nodes, _doc, **_kw: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_continued_tables",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_footnote_markers",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_cross_references",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.assess_toc_quality",
        lambda _nodes, _total_pages: TocQuality(
            score=0.0,
            entry_count=0,
            max_depth=0,
            page_coverage=0.0,
        ),
    )

    def _raise_missing_env(model):
        raise ValueError("missing env")

    monkeypatch.setattr(
        "autosarindex.llm.client.create_llm_client",
        _raise_missing_env,
    )

    idx = AutosarIndex("dummy.pdf")
    artifacts = idx.build(output_dir=str(tmp_path))
    idx.close()

    assert artifacts.toc_quality is not None
    assert artifacts.toc_quality.score == 0.0
    assert artifacts.json_data["toc"] == []


def test_build_llm_fallback_graceful_on_api_error(monkeypatch, tmp_path):
    """LLM API errors during ToC fallback should degrade gracefully."""

    def fake_open(_path: str):
        return _FakeBuildDoc()

    class _FakeAutoLlm:
        def __init__(self) -> None:
            self.closed = False

        def __call__(self, _system: str, _user: str) -> str:
            return "ok"

        def close(self) -> None:
            self.closed = True

    fake_llm = _FakeAutoLlm()

    def fake_client(model: str):
        return fake_llm

    def fake_toc_from_text(_text, _total_pages, _llm_callable):
        raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr("autosarindex.index.pymupdf.open", fake_open)
    monkeypatch.setattr(
        "autosarindex.index.generate_text", lambda _doc: "--- PAGE 1 ---\n"
    )
    monkeypatch.setattr("autosarindex.index.generate_preamble", lambda _doc: "pre")
    monkeypatch.setattr("autosarindex.index.extract_toc", lambda _doc: [])
    monkeypatch.setattr("autosarindex.index.build_tree", lambda _raw, _pages: [])
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_table_counts",
        lambda _nodes, _doc, **_kw: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_continued_tables",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_footnote_markers",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_cross_references",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.assess_toc_quality",
        lambda _nodes, _total_pages: TocQuality(
            score=0.0, entry_count=0, max_depth=0, page_coverage=0.0
        ),
    )
    monkeypatch.setattr("autosarindex.llm.client.create_llm_client", fake_client)
    monkeypatch.setattr(
        "autosarindex.llm.toc_fallback.generate_toc_from_text",
        fake_toc_from_text,
    )

    idx = AutosarIndex("dummy.pdf")
    artifacts = idx.build(output_dir=str(tmp_path))
    idx.close()

    # Should still produce artifacts with the original (empty) ToC
    assert artifacts.toc_quality is not None
    assert artifacts.toc_quality.score == 0.0
    assert artifacts.json_data["toc"] == []
    assert fake_llm.closed is True


def test_build_output_stem_override(monkeypatch, tmp_path):
    def fake_open(_path: str):
        return _FakeBuildDoc()

    monkeypatch.setattr("autosarindex.index.pymupdf.open", fake_open)
    monkeypatch.setattr(
        "autosarindex.index.generate_text", lambda _doc: "--- PAGE 1 ---\n"
    )
    monkeypatch.setattr("autosarindex.index.generate_preamble", lambda _doc: "pre")
    monkeypatch.setattr("autosarindex.index.extract_toc", lambda _doc: [])
    monkeypatch.setattr("autosarindex.index.build_tree", lambda _raw, _pages: [])
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_table_counts",
        lambda _nodes, _doc, **_kw: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_continued_tables",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_footnote_markers",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_cross_references",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.assess_toc_quality",
        lambda _nodes, _total_pages: TocQuality(
            score=1.0,
            entry_count=0,
            max_depth=0,
            page_coverage=0.0,
        ),
    )

    idx = AutosarIndex("dummy.pdf")
    artifacts = idx.build(output_dir=str(tmp_path), output_stem="custom:name")
    idx.close()

    assert artifacts.json_path is not None
    assert artifacts.text_path is not None
    assert artifacts.json_path.name == "custom_name.json"
    assert artifacts.text_path.name == "custom_name.txt"


def test_build_adds_autosar_metadata_and_requirements(monkeypatch, tmp_path):
    def fake_open(_path: str):
        return _FakeBuildDoc(pages=2)

    text = "\n".join(
        [
            "--- PAGE 1 ---",
            "AUTOSAR",
            "Specification of Communication",
            "AUTOSAR_SWS_COM",
            "Classic Platform",
            "Document Version 4.7.0",
            "Document Status Final",
            "R24-11",
            "[SWS_Com_00001] The COM module shall transmit I-PDUs.",
            "Figure 2.1: COM transmission flow",
            "I-PDU transmit trigger confirmation",
            "--- PAGE 2 ---",
            "Refer to AUTOSAR_SWS_PDUR.",
        ]
    )
    node = TocNode(
        title="2 Functional specification",
        level=1,
        start_page=1,
        end_page=2,
        node_id="0001",
    )

    monkeypatch.setattr("autosarindex.index.pymupdf.open", fake_open)
    monkeypatch.setattr("autosarindex.index.generate_text", lambda _doc: text)
    monkeypatch.setattr(
        "autosarindex.index.generate_preamble",
        lambda _doc: "Specification of Communication\nAUTOSAR_SWS_COM",
    )
    monkeypatch.setattr("autosarindex.index.extract_toc", lambda _doc: [])
    monkeypatch.setattr("autosarindex.index.build_tree", lambda _raw, _pages: [node])
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_table_counts",
        lambda _nodes, _doc, **_kw: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_continued_tables",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_footnote_markers",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_cross_references",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.assess_toc_quality",
        lambda _nodes, _total_pages: TocQuality(
            score=1.0,
            entry_count=1,
            max_depth=1,
            page_coverage=1.0,
        ),
    )

    idx = AutosarIndex("AUTOSAR_SWS_COM.pdf")
    artifacts = idx.build(output_dir=str(tmp_path))
    idx.close()

    assert artifacts.json_data["document_type"] == "autosar"
    assert artifacts.json_data["autosar_metadata"] == {
        "document_title": "Specification of Communication",
        "document_id": "AUTOSAR_SWS_COM",
        "release": "R24-11",
        "version": "4.7.0",
        "status": "Final",
        "platform": "Classic Platform",
    }
    autosar_requirements = artifacts.json_data["autosar_requirements"]
    assert autosar_requirements["total_count"] == 1
    assert autosar_requirements["ids"] == ["SWS_Com_00001"]
    assert autosar_requirements["ids_by_kind"] == {"definition": ["SWS_Com_00001"]}
    assert autosar_requirements["occurrence_count"] == 1
    assert autosar_requirements["occurrence_summary"] == {"definition": 1}
    assert autosar_requirements["occurrences_truncated"] is False
    assert autosar_requirements["occurrences"][0]["kind"] == "definition"
    requirement_index = autosar_requirements["index"]["SWS_Com_00001"]
    assert requirement_index["occurrence_count"] == 1
    assert requirement_index["definition_pages"] == [1]
    assert requirement_index["occurrences"][0]["section_title"] == (
        "2 Functional specification"
    )
    toc_node = artifacts.json_data["toc"][0]
    assert toc_node["autosar_section_type"] == "requirements"
    assert toc_node["requirement_ids"] == ["SWS_Com_00001"]
    assert toc_node["requirement_occurrence_count"] == 1
    assert toc_node["requirement_occurrence_summary"] == {"definition": 1}
    assert toc_node["normative_keywords"] == ["shall"]
    assert toc_node["referenced_documents"] == ["AUTOSAR_SWS_COM", "AUTOSAR_SWS_PDUR"]
    figure = artifacts.json_data["visual_index"]["figures"][0]
    assert figure["id"] == "Figure 2.1"
    assert figure["page"] == 1
    assert figure["section"]["node_id"] == "0001"
    assert "transmission" in [keyword.casefold() for keyword in figure["keywords"]]


def test_resolve_default_output_dir_uses_uid_namespaced_tempdir(monkeypatch):
    """Without env override, default lands in <tempdir>/autosarindex-<uid>."""
    import os
    import tempfile

    from autosarindex.index import resolve_default_output_dir

    monkeypatch.delenv("AUTOSARINDEX_OUTPUT_DIR", raising=False)
    monkeypatch.delenv("DATASHEETINDEX_OUTPUT_DIR", raising=False)
    resolved = Path(resolve_default_output_dir())
    assert resolved.parent == Path(tempfile.gettempdir())
    expected_leaf = (
        f"autosarindex-{os.getuid()}" if hasattr(os, "getuid") else "autosarindex"
    )
    assert resolved.name == expected_leaf


def test_resolve_default_output_dir_honours_env_var(monkeypatch, tmp_path):
    from autosarindex.index import resolve_default_output_dir

    monkeypatch.setenv("AUTOSARINDEX_OUTPUT_DIR", str(tmp_path / "deploy-pinned"))
    assert resolve_default_output_dir() == str(tmp_path / "deploy-pinned")


def test_resolve_default_output_dir_honours_legacy_env_var(monkeypatch, tmp_path):
    from autosarindex.index import resolve_default_output_dir

    monkeypatch.delenv("AUTOSARINDEX_OUTPUT_DIR", raising=False)
    monkeypatch.setenv(
        "DATASHEETINDEX_OUTPUT_DIR", str(tmp_path / "legacy-deploy-pinned")
    )
    assert resolve_default_output_dir() == str(tmp_path / "legacy-deploy-pinned")


def test_resolve_default_output_dir_blank_env_var_falls_through(monkeypatch):
    """Empty / whitespace env var must not be treated as a valid path."""
    import tempfile

    from autosarindex.index import resolve_default_output_dir

    for blank in ("", "   ", "\t\n"):
        monkeypatch.setenv("AUTOSARINDEX_OUTPUT_DIR", blank)
        monkeypatch.delenv("DATASHEETINDEX_OUTPUT_DIR", raising=False)
        resolved = Path(resolve_default_output_dir())
        assert resolved.parent == Path(tempfile.gettempdir())


def test_build_with_none_output_dir_writes_to_resolver_default(monkeypatch, tmp_path):
    """idx.build(output_dir=None) writes to the env-resolved default."""
    pinned = tmp_path / "env-pinned"
    monkeypatch.setenv("AUTOSARINDEX_OUTPUT_DIR", str(pinned))

    monkeypatch.setattr(
        "autosarindex.index.pymupdf.open", lambda _path: _FakeBuildDoc()
    )
    monkeypatch.setattr(
        "autosarindex.index.generate_text", lambda _doc: "--- PAGE 1 ---\n"
    )
    monkeypatch.setattr("autosarindex.index.generate_preamble", lambda _doc: "pre")
    monkeypatch.setattr("autosarindex.index.extract_toc", lambda _doc: [])
    monkeypatch.setattr("autosarindex.index.build_tree", lambda _raw, _pages: [])
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_table_counts",
        lambda _nodes, _doc, **_kw: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_continued_tables",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_footnote_markers",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_cross_references",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.assess_toc_quality",
        lambda _nodes, _total_pages: TocQuality(
            score=1.0, entry_count=0, max_depth=0, page_coverage=0.0
        ),
    )

    idx = AutosarIndex("dummy.pdf")
    artifacts = idx.build()
    idx.close()

    assert artifacts.json_path is not None
    assert pinned.exists()
    assert artifacts.json_path.parent == pinned


def test_build_with_blank_output_dir_falls_through_to_resolver(monkeypatch, tmp_path):
    """Empty / whitespace output_dir must not be treated as explicit-CWD."""
    pinned = tmp_path / "env-pinned"
    monkeypatch.setenv("AUTOSARINDEX_OUTPUT_DIR", str(pinned))

    monkeypatch.setattr(
        "autosarindex.index.pymupdf.open", lambda _path: _FakeBuildDoc()
    )
    monkeypatch.setattr(
        "autosarindex.index.generate_text", lambda _doc: "--- PAGE 1 ---\n"
    )
    monkeypatch.setattr("autosarindex.index.generate_preamble", lambda _doc: "pre")
    monkeypatch.setattr("autosarindex.index.extract_toc", lambda _doc: [])
    monkeypatch.setattr("autosarindex.index.build_tree", lambda _raw, _pages: [])
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_table_counts",
        lambda _nodes, _doc, **_kw: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_continued_tables",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_footnote_markers",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.enrich_with_cross_references",
        lambda _nodes, _text: _nodes,
    )
    monkeypatch.setattr(
        "autosarindex.index.assess_toc_quality",
        lambda _nodes, _total_pages: TocQuality(
            score=1.0, entry_count=0, max_depth=0, page_coverage=0.0
        ),
    )

    for blank in ("", "   ", "\t"):
        idx = AutosarIndex("dummy.pdf")
        artifacts = idx.build(output_dir=blank)
        idx.close()
        assert artifacts.json_path is not None
        assert artifacts.json_path.parent == pinned
