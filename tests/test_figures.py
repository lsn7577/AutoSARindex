"""Tests for figure caption indexing."""

from typing import cast

import pytest

from autosarindex.core.figures import (
    build_figure_index,
    get_figure_context,
    search_figure_index,
)
from autosarindex.models import TocNode


def _make_text(*page_texts: str) -> str:
    parts: list[str] = []
    for page, text in enumerate(page_texts, start=1):
        parts.append(f"--- PAGE {page} ---")
        parts.append(text)
    return "\n".join(parts)


def test_build_figure_index_captures_caption_section_and_keywords():
    text = _make_text(
        "Before text\n"
        "[SWS_Os_00001] The task shall start.\n"
        "Figure 7.11: Task state model\n"
        "READY RUNNING WAITING SUSPENDED transition StartOS\n",
        "Figure 8-2: Startup flow\nStartOS initializes the kernel.",
    )
    node = TocNode(
        title="7.4 Task management",
        level=2,
        start_page=1,
        end_page=1,
        node_id="0007",
        breadcrumb="7 Functional specification > 7.4 Task management",
    )

    figures = build_figure_index(text, [node])

    assert len(figures) == 2
    first = figures[0]
    assert first["id"] == "Figure 7.11"
    assert first["number"] == "7.11"
    assert first["title"] == "Task state model"
    assert first["page"] == 1
    section = cast("dict[str, object]", first["section"])
    keywords = cast("list[str]", first["keywords"])
    inspect_hint = cast("dict[str, object]", first["inspect_hint"])
    assert section["node_id"] == "0007"
    assert "READY" in keywords
    assert first["nearby_requirement_ids"] == ["SWS_Os_00001"]
    assert inspect_hint["page"] == 1


def test_search_and_get_figure_context():
    figures: list[dict[str, object]] = [
        {
            "id": "Figure 7.11",
            "number": "7.11",
            "title": "Task state model",
            "page": 5,
            "keywords": ["Task", "READY", "RUNNING"],
            "snippet": "Figure 7.11: Task state model READY RUNNING",
        }
    ]

    result = search_figure_index(figures, "running")
    context = get_figure_context(figures, "7.11")

    assert result["total_matches"] == 1
    results = cast("list[dict[str, object]]", result["results"])
    assert results[0]["id"] == "Figure 7.11"
    assert context["page"] == 5


def test_search_figure_index_validates_query():
    with pytest.raises(ValueError, match="query"):
        search_figure_index([], "")


def test_build_figure_index_merges_wrapped_caption_title():
    text = _make_text(
        "Figure 7.5: States of an explicit synchronized ScheduleTable "
        "(not all conditions for\n"
        "transitions are shown)\n"
        "More text."
    )

    figures = build_figure_index(text, [])

    assert figures[0]["title"] == (
        "States of an explicit synchronized ScheduleTable "
        "(not all conditions for transitions are shown)"
    )
