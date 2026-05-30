"""Data models for autosarindex artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TocNode:
    """A node in the enriched Table of Contents tree."""

    title: str
    level: int
    start_page: int
    end_page: int = 0
    node_id: str = ""
    breadcrumb: str = ""
    boilerplate_category: str = ""
    has_tables: bool = False
    table_count: int = 0
    summary: str = ""
    continued_tables: list[str] = field(default_factory=list)
    footnote_markers: list[str] = field(default_factory=list)
    cross_references: list[dict] = field(default_factory=list)
    autosar_section_type: str = ""
    requirement_ids: list[str] = field(default_factory=list)
    requirement_count: int = 0
    requirement_occurrences: list[dict] = field(default_factory=list)
    requirement_occurrence_count: int = 0
    requirement_occurrence_summary: dict[str, int] = field(default_factory=dict)
    normative_keywords: list[str] = field(default_factory=list)
    referenced_documents: list[str] = field(default_factory=list)
    nodes: list[TocNode] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dictionary."""
        result: dict = {
            "node_id": self.node_id,
            "title": self.title,
            "level": self.level,
            "start_page": self.start_page,
            "end_page": self.end_page,
            "has_tables": self.has_tables,
            "table_count": self.table_count,
        }
        if self.breadcrumb:
            result["breadcrumb"] = self.breadcrumb
        if self.boilerplate_category:
            result["boilerplate_category"] = self.boilerplate_category
        if self.summary:
            result["summary"] = self.summary
        if self.continued_tables:
            result["continued_tables"] = self.continued_tables
        if self.footnote_markers:
            result["footnote_markers"] = self.footnote_markers
        if self.cross_references:
            result["cross_references"] = self.cross_references
        if self.autosar_section_type:
            result["autosar_section_type"] = self.autosar_section_type
        if self.requirement_ids:
            result["requirement_ids"] = self.requirement_ids
        if self.requirement_count:
            result["requirement_count"] = self.requirement_count
        if self.requirement_occurrences:
            result["requirement_occurrences"] = self.requirement_occurrences
        if self.requirement_occurrence_count:
            result["requirement_occurrence_count"] = self.requirement_occurrence_count
        if self.requirement_occurrence_summary:
            result["requirement_occurrence_summary"] = (
                self.requirement_occurrence_summary
            )
        if self.normative_keywords:
            result["normative_keywords"] = self.normative_keywords
        if self.referenced_documents:
            result["referenced_documents"] = self.referenced_documents
        if self.nodes:
            result["nodes"] = [child.to_dict() for child in self.nodes]
        return result


@dataclass
class TocQuality:
    """Quality assessment for the extracted ToC."""

    score: float = 0.0
    entry_count: int = 0
    max_depth: int = 0
    page_coverage: float = 0.0
    recommend_summaries: bool = False
    details: str = ""


@dataclass
class AutosarArtifacts:
    """Output of the autosarindex build process."""

    json_path: Path | None = None
    text_path: Path | None = None
    json_data: dict = field(default_factory=dict)
    text_content: str = ""
    toc_quality: TocQuality | None = None


DatasheetArtifacts = AutosarArtifacts


def flatten_nodes(nodes: list[TocNode]) -> list[TocNode]:
    """Collect all nodes into a flat list via depth-first traversal."""
    result: list[TocNode] = []
    for node in nodes:
        result.append(node)
        if node.nodes:
            result.extend(flatten_nodes(node.nodes))
    return result
