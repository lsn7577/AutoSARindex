"""Tests for data models."""

from autosarindex.models import (
    AutosarArtifacts,
    TocNode,
    TocQuality,
    flatten_nodes,
)


def test_toc_node_defaults():
    node = TocNode(title="Section 1", level=1, start_page=1)
    assert node.end_page == 0
    assert node.node_id == ""
    assert node.has_tables is False
    assert node.table_count == 0
    assert node.continued_tables == []
    assert node.footnote_markers == []
    assert node.cross_references == []
    assert node.autosar_section_type == ""
    assert node.requirement_ids == []
    assert node.requirement_count == 0
    assert node.requirement_occurrences == []
    assert node.requirement_occurrence_count == 0
    assert node.requirement_occurrence_summary == {}
    assert node.normative_keywords == []
    assert node.referenced_documents == []
    assert node.nodes == []


def test_toc_node_to_dict_simple():
    node = TocNode(
        title="Overview",
        level=1,
        start_page=3,
        end_page=5,
        node_id="0001",
        has_tables=True,
        table_count=2,
    )
    d = node.to_dict()
    assert d["node_id"] == "0001"
    assert d["title"] == "Overview"
    assert d["level"] == 1
    assert d["start_page"] == 3
    assert d["end_page"] == 5
    assert d["has_tables"] is True
    assert d["table_count"] == 2
    assert "nodes" not in d


def test_toc_node_to_dict_nested():
    child = TocNode(title="Sub", level=2, start_page=4, end_page=5, node_id="0002")
    parent = TocNode(
        title="Parent",
        level=1,
        start_page=3,
        end_page=5,
        node_id="0001",
        nodes=[child],
    )
    d = parent.to_dict()
    assert "nodes" in d
    assert len(d["nodes"]) == 1
    assert d["nodes"][0]["title"] == "Sub"
    assert d["nodes"][0]["node_id"] == "0002"


def test_toc_node_to_dict_round_trip():
    """Verify to_dict produces a structure that could be serialized and recreated."""
    tree = TocNode(
        title="Root",
        level=1,
        start_page=1,
        end_page=10,
        node_id="0001",
        nodes=[
            TocNode(
                title="A",
                level=2,
                start_page=1,
                end_page=5,
                node_id="0002",
                nodes=[
                    TocNode(
                        title="A.1",
                        level=3,
                        start_page=1,
                        end_page=3,
                        node_id="0003",
                    ),
                ],
            ),
            TocNode(
                title="B",
                level=2,
                start_page=6,
                end_page=10,
                node_id="0004",
            ),
        ],
    )
    d = tree.to_dict()
    assert len(d["nodes"]) == 2
    assert len(d["nodes"][0]["nodes"]) == 1
    assert "nodes" not in d["nodes"][1]


def test_toc_quality_defaults():
    q = TocQuality()
    assert q.score == 0.0
    assert q.entry_count == 0
    assert q.recommend_summaries is False


def test_toc_node_to_dict_omits_empty_enrichments():
    """Empty enrichment lists should not appear in to_dict output."""
    node = TocNode(title="X", level=1, start_page=1, end_page=2, node_id="0001")
    d = node.to_dict()
    assert "continued_tables" not in d
    assert "footnote_markers" not in d
    assert "cross_references" not in d
    assert "summary" not in d
    assert "breadcrumb" not in d
    assert "boilerplate_category" not in d
    assert "autosar_section_type" not in d
    assert "requirement_ids" not in d
    assert "requirement_count" not in d
    assert "requirement_occurrences" not in d
    assert "requirement_occurrence_count" not in d
    assert "requirement_occurrence_summary" not in d
    assert "normative_keywords" not in d
    assert "referenced_documents" not in d


def test_toc_node_to_dict_includes_breadcrumb_and_boilerplate():
    """Non-empty breadcrumb and boilerplate_category should appear in to_dict."""
    node = TocNode(
        title="Revision History",
        level=1,
        start_page=1,
        end_page=2,
        node_id="0001",
        breadcrumb="Document Info > Revision History",
        boilerplate_category="revision",
    )
    d = node.to_dict()
    assert d["breadcrumb"] == "Document Info > Revision History"
    assert d["boilerplate_category"] == "revision"


def test_toc_node_to_dict_includes_enrichments():
    """Non-empty enrichment fields should appear in to_dict output."""
    node = TocNode(
        title="X",
        level=1,
        start_page=1,
        end_page=2,
        node_id="0001",
        continued_tables=["Table 1 Electrical Specs"],
        footnote_markers=["1)", "Note 1"],
        cross_references=[
            {"text": "see Table 2", "type": "table", "target": "Table 2"},
        ],
    )
    d = node.to_dict()
    assert d["continued_tables"] == ["Table 1 Electrical Specs"]
    assert d["footnote_markers"] == ["1)", "Note 1"]
    assert len(d["cross_references"]) == 1
    assert d["cross_references"][0]["type"] == "table"


def test_toc_node_to_dict_includes_autosar_enrichments():
    node = TocNode(
        title="Functional specification",
        level=1,
        start_page=1,
        end_page=2,
        node_id="0001",
        autosar_section_type="requirements",
        requirement_ids=["SWS_Com_00001"],
        requirement_count=1,
        requirement_occurrences=[
            {
                "id": "SWS_Com_00001",
                "kind": "definition",
                "page": 1,
                "snippet": "[SWS_Com_00001] shall apply.",
            }
        ],
        requirement_occurrence_count=1,
        requirement_occurrence_summary={"definition": 1},
        normative_keywords=["shall"],
        referenced_documents=["AUTOSAR_SWS_PDUR"],
    )
    d = node.to_dict()
    assert d["autosar_section_type"] == "requirements"
    assert d["requirement_ids"] == ["SWS_Com_00001"]
    assert d["requirement_count"] == 1
    assert d["requirement_occurrence_count"] == 1
    assert d["requirement_occurrence_summary"] == {"definition": 1}
    assert d["requirement_occurrences"][0]["kind"] == "definition"
    assert d["normative_keywords"] == ["shall"]
    assert d["referenced_documents"] == ["AUTOSAR_SWS_PDUR"]


def test_flatten_nodes_empty():
    assert flatten_nodes([]) == []


def test_flatten_nodes_flat():
    nodes = [
        TocNode(title="A", level=1, start_page=1),
        TocNode(title="B", level=1, start_page=2),
    ]
    flat = flatten_nodes(nodes)
    assert len(flat) == 2
    assert flat[0].title == "A"
    assert flat[1].title == "B"


def test_flatten_nodes_nested():
    child1 = TocNode(title="A.1", level=2, start_page=1)
    child2 = TocNode(title="A.2", level=2, start_page=2)
    parent = TocNode(title="A", level=1, start_page=1, nodes=[child1, child2])
    sibling = TocNode(title="B", level=1, start_page=3)
    flat = flatten_nodes([parent, sibling])
    assert len(flat) == 4
    assert [n.title for n in flat] == ["A", "A.1", "A.2", "B"]


def test_datasheet_artifacts_defaults():
    a = AutosarArtifacts()
    assert a.json_path is None
    assert a.text_path is None
    assert a.json_data == {}
    assert a.text_content == ""
    assert a.toc_quality is None
