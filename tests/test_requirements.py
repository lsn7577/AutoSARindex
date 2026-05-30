"""Tests for AUTOSAR requirement enrichment."""

from autosarindex.core.requirements import (
    build_requirement_index,
    collect_requirement_ids,
    collect_requirement_ids_by_kind,
    collect_requirement_occurrences,
    enrich_with_autosar_requirements,
    extract_requirement_ids,
    extract_requirement_occurrences,
    summarize_requirement_occurrences,
)
from autosarindex.models import TocNode


def _make_text(*page_texts: str) -> str:
    parts: list[str] = []
    for i, text in enumerate(page_texts, start=1):
        parts.append(f"--- PAGE {i} ---")
        parts.append(text)
    return "\n".join(parts)


def test_extract_requirement_ids_deduplicates():
    text = "[SWS_Com_00001] shall apply. [SWS_Com_00001] repeated."
    assert extract_requirement_ids(text) == ["SWS_Com_00001"]


def test_enrich_with_autosar_requirements_scopes_to_node_pages():
    text = _make_text(
        "[SWS_Com_00001] The module shall transmit I-PDUs.",
        "[RS_BRF_01234] The stack should reference AUTOSAR_SWS_PDUR.",
    )
    child = TocNode(title="2.1 Transmission", level=2, start_page=1, end_page=1)
    parent = TocNode(
        title="2 Functional specification",
        level=1,
        start_page=1,
        end_page=2,
        nodes=[child],
    )

    enrich_with_autosar_requirements([parent], text)

    assert parent.requirement_ids == ["SWS_Com_00001", "RS_BRF_01234"]
    assert parent.requirement_count == 2
    assert parent.requirement_occurrence_count == 2
    assert parent.requirement_occurrence_summary == {
        "definition": 1,
        "reference": 1,
    }
    assert parent.autosar_section_type == "requirements"
    assert parent.normative_keywords == ["shall", "should"]
    assert parent.referenced_documents == ["AUTOSAR_SWS_PDUR"]
    assert child.requirement_ids == ["SWS_Com_00001"]
    assert child.requirement_count == 1
    assert child.requirement_occurrences[0]["kind"] == "definition"


def test_extract_requirement_occurrences_classifies_contexts():
    definition = extract_requirement_occurrences(
        _make_text("[SWS_Com_00001] The module shall transmit I-PDUs."),
        section_title="7 Functional specification",
    )
    reference = extract_requirement_occurrences(
        _make_text("See [SWS_Com_00002] for timing constraints."),
        section_title="7 Functional specification",
    )
    specified_reference = extract_requirement_occurrences(
        _make_text("This is specified in [TPS_STDT_00078]."),
        section_title="7 Functional specification",
    )
    traceability = extract_requirement_occurrences(
        _make_text("[SWS_Com_00003] traces to RS_BRF_00001."),
        section_title="6 Requirements Tracing",
    )
    change = extract_requirement_occurrences(
        _make_text("[SWS_Com_00004] moved to another chapter."),
        section_title="9 Change History",
    )

    assert definition[0].kind == "definition"
    assert reference[0].kind == "reference"
    assert specified_reference[0].kind == "reference"
    assert traceability[0].kind == "traceability"
    assert change[0].kind == "change_history"
    assert definition[0].page == 1
    assert definition[0].to_dict()["id"] == "SWS_Com_00001"


def test_summarize_requirement_occurrences_omits_zero_counts():
    occurrences = extract_requirement_occurrences(
        _make_text(
            "[SWS_Com_00001] The module shall start.",
            "See [SWS_Com_00002].",
        ),
        section_title="Functional specification",
    )

    assert summarize_requirement_occurrences(occurrences) == {
        "definition": 1,
        "reference": 1,
    }
    assert collect_requirement_ids_by_kind(occurrences) == {
        "definition": ["SWS_Com_00001"],
        "reference": ["SWS_Com_00002"],
    }


def test_collect_requirement_ids_preserves_first_seen_order():
    nodes = [
        TocNode(
            title="A",
            level=1,
            start_page=1,
            requirement_ids=["SWS_A_00001", "SWS_A_00002"],
        ),
        TocNode(
            title="B",
            level=1,
            start_page=2,
            requirement_ids=["SWS_A_00002", "SWS_B_00001"],
        ),
    ]

    assert collect_requirement_ids(nodes) == [
        "SWS_A_00001",
        "SWS_A_00002",
        "SWS_B_00001",
    ]


def test_collect_requirement_occurrences_from_tree():
    node = TocNode(
        title="A",
        level=1,
        start_page=1,
        requirement_occurrences=[
            {
                "id": "SWS_A_00001",
                "kind": "definition",
                "page": 1,
                "snippet": "[SWS_A_00001] shall apply.",
            }
        ],
    )

    occurrences = collect_requirement_occurrences([node])

    assert len(occurrences) == 1
    assert occurrences[0].requirement_id == "SWS_A_00001"
    assert occurrences[0].kind == "definition"


def test_collect_requirement_occurrences_deduplicates_parent_child_overlap():
    occurrence = {
        "id": "SWS_A_00001",
        "kind": "definition",
        "page": 1,
        "snippet": "[SWS_A_00001] shall apply.",
    }
    child = TocNode(
        title="A.1",
        level=2,
        start_page=1,
        requirement_occurrences=[occurrence],
    )
    parent = TocNode(
        title="A",
        level=1,
        start_page=1,
        requirement_occurrences=[occurrence],
        nodes=[child],
    )

    occurrences = collect_requirement_occurrences([parent])

    assert len(occurrences) == 1


def test_build_requirement_index_prefers_specific_section():
    occurrence = {
        "id": "SWS_A_00001",
        "kind": "definition",
        "page": 2,
        "snippet": "[SWS_A_00001] shall apply.",
    }
    child = TocNode(
        title="A.1 Specific",
        level=2,
        start_page=2,
        end_page=2,
        node_id="0002",
        breadcrumb="A > A.1 Specific",
        requirement_occurrences=[occurrence],
    )
    parent = TocNode(
        title="A",
        level=1,
        start_page=1,
        end_page=3,
        node_id="0001",
        breadcrumb="A",
        requirement_occurrences=[occurrence],
        nodes=[child],
    )

    index = build_requirement_index([parent])

    entry = index["SWS_A_00001"]
    assert entry["occurrence_count"] == 1
    assert entry["kind_counts"] == {"definition": 1}
    assert entry["definition_pages"] == [2]
    assert entry["sections"][0]["node_id"] == "0002"
    assert entry["occurrences"][0]["section_title"] == "A.1 Specific"
