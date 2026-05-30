"""AUTOSAR requirement and normative-language enrichment."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from autosarindex.core.textfile import extract_section_text
from autosarindex.models import TocNode, flatten_nodes

RequirementOccurrenceKind = Literal[
    "definition", "reference", "traceability", "change_history"
]
REQUIREMENT_OCCURRENCE_KINDS: tuple[RequirementOccurrenceKind, ...] = (
    "definition",
    "reference",
    "traceability",
    "change_history",
)

_REQUIREMENT_ID_RE = re.compile(
    r"\[((?:SWS|RS|SRS|PRS|TPS)_[A-Za-z0-9][A-Za-z0-9_]*_\d{5})\]"
)
_PAGE_MARKER_RE = re.compile(r"--- PAGE (\d+) ---")
_TRACEABILITY_TITLE_RE = re.compile(r"\b(requirements?\s+tracing|traceability)\b", re.I)
_CHANGE_HISTORY_TITLE_RE = re.compile(r"\b(change|revision|history)\b", re.I)
_REFERENCE_CONTEXT_RE = re.compile(
    r"\b(see|refer(?:s|red|ring)?\s+to|reference[sd]?|trace[sd]?|"
    r"specified\s+in|derived\s+from|satisf(?:y|ies|ied)|linked\s+to)\b",
    re.IGNORECASE,
)
_NORMATIVE_KEYWORD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("shall not", re.compile(r"\bshall\s+not\b", re.IGNORECASE)),
    ("shall", re.compile(r"\bshall\b", re.IGNORECASE)),
    ("must", re.compile(r"\bmust\b", re.IGNORECASE)),
    ("should", re.compile(r"\bshould\b", re.IGNORECASE)),
    ("may", re.compile(r"\bmay\b", re.IGNORECASE)),
)
_AUTOSAR_DOCUMENT_RE = re.compile(r"\bAUTOSAR_[A-Za-z0-9_]+\b")


@dataclass(frozen=True)
class RequirementOccurrence:
    """One occurrence of an AUTOSAR requirement ID in extracted text."""

    requirement_id: str
    kind: RequirementOccurrenceKind
    page: int
    snippet: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "id": self.requirement_id,
            "kind": self.kind,
            "page": self.page,
            "snippet": self.snippet,
        }


def enrich_with_autosar_requirements(
    nodes: list[TocNode], text_content: str
) -> list[TocNode]:
    """Populate AUTOSAR-specific fields for each ToC node."""
    _requirements_recursive(nodes, text_content)
    return nodes


def collect_requirement_ids(nodes: Iterable[TocNode]) -> list[str]:
    """Collect unique requirement IDs from a node tree in first-seen order."""
    result: list[str] = []
    seen: set[str] = set()
    for node in flatten_nodes(list(nodes)):
        for requirement_id in node.requirement_ids:
            if requirement_id not in seen:
                seen.add(requirement_id)
                result.append(requirement_id)
    return result


def collect_requirement_occurrences(
    nodes: Iterable[TocNode],
) -> list[RequirementOccurrence]:
    """Collect occurrence records from a node tree."""
    result: list[RequirementOccurrence] = []
    seen: set[tuple[str, str, int, str]] = set()
    for node in flatten_nodes(list(nodes)):
        for occurrence in node.requirement_occurrences:
            item = _coerce_occurrence(occurrence)
            key = (item.requirement_id, item.kind, item.page, item.snippet)
            if key not in seen:
                seen.add(key)
                result.append(item)
    return result


def summarize_requirement_occurrences(
    occurrences: Iterable[RequirementOccurrence | dict],
) -> dict[str, int]:
    """Count requirement occurrences by semantic kind."""
    summary = {
        "definition": 0,
        "reference": 0,
        "traceability": 0,
        "change_history": 0,
    }
    for occurrence in occurrences:
        item = _coerce_occurrence(occurrence)
        summary[item.kind] += 1
    return {key: value for key, value in summary.items() if value}


def collect_requirement_ids_by_kind(
    occurrences: Iterable[RequirementOccurrence | dict],
) -> dict[str, list[str]]:
    """Collect unique requirement IDs grouped by occurrence kind."""
    result: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for occurrence in occurrences:
        item = _coerce_occurrence(occurrence)
        result.setdefault(item.kind, [])
        seen.setdefault(item.kind, set())
        if item.requirement_id not in seen[item.kind]:
            seen[item.kind].add(item.requirement_id)
            result[item.kind].append(item.requirement_id)
    return result


def build_requirement_index(nodes: Iterable[TocNode]) -> dict[str, dict]:
    """Build a compact requirement lookup index from enriched ToC nodes.

    Parent sections include child page ranges, so occurrence records can appear
    more than once in the tree. For lookup, keep one copy and attach it to the
    narrowest matching section so requirement queries land on the most specific
    available context.
    """
    best_by_occurrence: dict[
        tuple[str, str, int, str],
        tuple[tuple[int, int], int, RequirementOccurrence, TocNode],
    ] = {}
    for order, node in enumerate(flatten_nodes(list(nodes))):
        span = max(0, node.end_page - node.start_page)
        score = (span, -node.level)
        for occurrence in node.requirement_occurrences:
            item = _coerce_occurrence(occurrence)
            key = (item.requirement_id, item.kind, item.page, item.snippet)
            current = best_by_occurrence.get(key)
            if current is None or score < current[0]:
                best_by_occurrence[key] = (score, order, item, node)

    selected = sorted(
        best_by_occurrence.values(),
        key=lambda value: (value[2].page, value[1]),
    )
    result: dict[str, dict] = {}
    for _score, _order, occurrence, node in selected:
        entry = _requirement_index_entry(result, occurrence.requirement_id)
        _add_requirement_index_occurrence(entry, occurrence)
        section = {
            "node_id": node.node_id,
            "title": node.title,
            "breadcrumb": node.breadcrumb,
            "start_page": node.start_page,
            "end_page": node.end_page,
        }
        if section not in entry["sections"]:
            entry["sections"].append(section)
        entry["occurrences"].append(
            {
                "kind": occurrence.kind,
                "page": occurrence.page,
                "snippet": occurrence.snippet,
                "node_id": node.node_id,
                "section_title": node.title,
                "breadcrumb": node.breadcrumb,
            }
        )
    return result


def build_requirement_index_from_occurrences(
    occurrences: Iterable[RequirementOccurrence | dict],
) -> dict[str, dict]:
    """Build a requirement lookup index when no ToC nodes are available."""
    result: dict[str, dict] = {}
    seen: set[tuple[str, str, int, str]] = set()
    for occurrence in occurrences:
        item = _coerce_occurrence(occurrence)
        key = (item.requirement_id, item.kind, item.page, item.snippet)
        if key in seen:
            continue
        seen.add(key)
        entry = _requirement_index_entry(result, item.requirement_id)
        _add_requirement_index_occurrence(entry, item)
        entry["occurrences"].append(
            {
                "kind": item.kind,
                "page": item.page,
                "snippet": item.snippet,
                "node_id": "",
                "section_title": "",
                "breadcrumb": "",
            }
        )
    return result


def extract_requirement_ids(text: str) -> list[str]:
    """Extract unique AUTOSAR requirement IDs from text."""
    return _deduplicate(_REQUIREMENT_ID_RE.findall(text))


def extract_requirement_occurrences(
    text: str,
    *,
    section_title: str = "",
) -> list[RequirementOccurrence]:
    """Extract requirement occurrences with page and semantic kind."""
    occurrences: list[RequirementOccurrence] = []
    current_page = 0
    for line in text.splitlines():
        page_match = _PAGE_MARKER_RE.match(line.strip())
        if page_match:
            current_page = int(page_match.group(1))
            continue
        for match in _REQUIREMENT_ID_RE.finditer(line):
            occurrence_id = match.group(1)
            occurrences.append(
                RequirementOccurrence(
                    requirement_id=occurrence_id,
                    kind=_classify_occurrence(section_title, line),
                    page=current_page,
                    snippet=_build_snippet(line, match.start(), match.end()),
                )
            )
    return occurrences


def _requirements_recursive(nodes: list[TocNode], text_content: str) -> None:
    for node in nodes:
        section_text = extract_section_text(
            text_content, node.start_page, node.end_page
        )
        occurrences = extract_requirement_occurrences(
            section_text,
            section_title=node.title,
        )
        node.requirement_occurrences = [item.to_dict() for item in occurrences]
        node.requirement_occurrence_count = len(occurrences)
        node.requirement_occurrence_summary = summarize_requirement_occurrences(
            occurrences
        )
        node.requirement_ids = _deduplicate(
            occurrence.requirement_id for occurrence in occurrences
        )
        node.requirement_count = len(node.requirement_ids)
        node.normative_keywords = _detect_normative_keywords(section_text)
        node.referenced_documents = _extract_referenced_documents(section_text)
        node.autosar_section_type = _classify_autosar_section(
            node.title,
            has_requirements=bool(node.requirement_ids),
            referenced_documents=node.referenced_documents,
        )
        if node.nodes:
            _requirements_recursive(node.nodes, text_content)


def _classify_occurrence(
    section_title: str,
    line: str,
) -> RequirementOccurrenceKind:
    title = section_title.casefold()
    if _TRACEABILITY_TITLE_RE.search(title):
        return "traceability"
    if _CHANGE_HISTORY_TITLE_RE.search(title):
        return "change_history"
    if _REFERENCE_CONTEXT_RE.search(line):
        return "reference"
    return "definition"


def _build_snippet(line: str, start: int, end: int, context_chars: int = 100) -> str:
    left = max(0, start - context_chars)
    right = min(len(line), end + context_chars)
    snippet = " ".join(line[left:right].split())
    if left > 0:
        snippet = f"...{snippet}"
    if right < len(line):
        snippet = f"{snippet}..."
    return snippet


def _coerce_occurrence(
    occurrence: RequirementOccurrence | dict,
) -> RequirementOccurrence:
    if isinstance(occurrence, RequirementOccurrence):
        return occurrence
    return RequirementOccurrence(
        requirement_id=str(occurrence["id"]),
        kind=occurrence["kind"],
        page=int(occurrence["page"]),
        snippet=str(occurrence["snippet"]),
    )


def _detect_normative_keywords(text: str) -> list[str]:
    result: list[str] = []
    for label, pattern in _NORMATIVE_KEYWORD_PATTERNS:
        if pattern.search(text):
            result.append(label)
    return result


def _extract_referenced_documents(text: str) -> list[str]:
    return _deduplicate(_AUTOSAR_DOCUMENT_RE.findall(text))


def _classify_autosar_section(
    title: str,
    *,
    has_requirements: bool,
    referenced_documents: list[str],
) -> str:
    normalized = title.casefold()
    if has_requirements:
        return "requirements"
    if "reference" in normalized or referenced_documents:
        return "references"
    if (
        "acronym" in normalized
        or "abbreviation" in normalized
        or "glossary" in normalized
    ):
        return "glossary"
    if "change" in normalized or "revision" in normalized or "history" in normalized:
        return "change_history"
    if "introduction" in normalized or "scope" in normalized:
        return "overview"
    if "configuration" in normalized:
        return "configuration"
    return ""


def _deduplicate(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _append_unique(values: list, value: object) -> None:
    if value not in values:
        values.append(value)


def _requirement_index_entry(
    result: dict[str, dict],
    requirement_id: str,
) -> dict:
    return result.setdefault(
        requirement_id,
        {
            "id": requirement_id,
            "occurrence_count": 0,
            "kind_counts": {},
            "pages": [],
            "definition_pages": [],
            "reference_pages": [],
            "traceability_pages": [],
            "change_history_pages": [],
            "sections": [],
            "occurrences": [],
        },
    )


def _add_requirement_index_occurrence(
    entry: dict,
    occurrence: RequirementOccurrence,
) -> None:
    entry["occurrence_count"] += 1
    kind_counts = entry["kind_counts"]
    kind_counts[occurrence.kind] = kind_counts.get(occurrence.kind, 0) + 1
    _append_unique(entry["pages"], occurrence.page)
    _append_unique(entry[f"{occurrence.kind}_pages"], occurrence.page)
