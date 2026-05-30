"""Figure caption indexing for visual navigation."""

from __future__ import annotations

import re
from dataclasses import dataclass

from autosarindex.core.requirements import extract_requirement_ids
from autosarindex.models import TocNode, flatten_nodes

_PAGE_MARKER_RE = re.compile(r"--- PAGE (\d+) ---")
_FIGURE_CAPTION_RE = re.compile(
    r"(?P<label>\b(?:Figure|Fig\.)\s+(?P<number>\d+(?:[.\-]\d+)*))"
    r"\s*[:\-]\s*(?P<title>[^\r\n]+)",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_STOPWORDS = {
    "and",
    "are",
    "autosar",
    "can",
    "for",
    "from",
    "has",
    "have",
    "into",
    "not",
    "shall",
    "should",
    "that",
    "the",
    "this",
    "with",
}


@dataclass(frozen=True)
class FigureEntry:
    """One figure caption occurrence in extracted text."""

    figure_id: str
    number: str
    title: str
    page: int
    section: dict[str, object]
    keywords: list[str]
    nearby_requirement_ids: list[str]
    snippet: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.figure_id,
            "kind": "figure",
            "number": self.number,
            "title": self.title,
            "page": self.page,
            "section": self.section,
            "keywords": self.keywords,
            "nearby_requirement_ids": self.nearby_requirement_ids,
            "snippet": self.snippet,
            "inspect_hint": {
                "page": self.page,
                "reason": (
                    "Use inspect_page on this page if the caption context is "
                    "insufficient."
                ),
            },
        }


def build_figure_index(
    text_content: str,
    nodes: list[TocNode],
    *,
    nearby_chars: int = 1000,
) -> list[dict[str, object]]:
    """Build a figure navigation index from page-matched text."""
    result: list[dict[str, object]] = []
    seen: set[tuple[str, int, str]] = set()
    for page, page_text in _iter_pages(text_content):
        for match in _FIGURE_CAPTION_RE.finditer(page_text):
            title = _extend_caption_title(page_text, match)
            number = match.group("number")
            figure_id = f"Figure {number}"
            snippet = _build_snippet(
                page_text,
                match.start(),
                match.end(),
                context_chars=nearby_chars // 2,
            )
            nearby_text = _build_snippet(
                page_text,
                match.start(),
                match.end(),
                context_chars=nearby_chars,
            )
            key = (figure_id.casefold(), page, title.casefold())
            if key in seen:
                continue
            seen.add(key)
            entry = FigureEntry(
                figure_id=figure_id,
                number=number,
                title=title,
                page=page,
                section=_find_section(page, nodes),
                keywords=_extract_keywords(" ".join([title, nearby_text])),
                nearby_requirement_ids=extract_requirement_ids(nearby_text),
                snippet=snippet,
            )
            result.append(entry.to_dict())
    return result


def search_figure_index(
    figures: list[dict[str, object]],
    query: str,
    *,
    max_results: int = 20,
) -> dict[str, object]:
    """Search figure captions and keywords."""
    normalized_query = query.casefold().strip()
    if not normalized_query:
        raise ValueError("query must not be empty")
    if max_results < 1:
        raise ValueError("max_results must be at least 1")

    query_terms = _extract_keywords(normalized_query)
    scored: list[tuple[int, dict[str, object]]] = []
    for figure in figures:
        haystack = _figure_search_text(figure)
        score = 0
        if normalized_query in haystack:
            score += 10
        for term in query_terms:
            if term.casefold() in haystack:
                score += 2
        if score:
            scored.append((score, figure))

    scored.sort(key=lambda item: (-item[0], int(item[1].get("page", 0))))
    results = [item for _score, item in scored[:max_results]]
    return {
        "query": query,
        "total_matches": len(scored),
        "truncated": len(scored) > max_results,
        "results": results,
    }


def get_figure_context(
    figures: list[dict[str, object]],
    figure_id: str,
) -> dict[str, object]:
    """Return one figure entry by ID, number, or exact caption title."""
    needle = _normalize_figure_lookup(figure_id)
    for figure in figures:
        candidates = {
            _normalize_figure_lookup(str(figure.get("id", ""))),
            _normalize_figure_lookup(str(figure.get("number", ""))),
            _normalize_figure_lookup(str(figure.get("title", ""))),
        }
        if needle in candidates:
            return dict(figure)
    raise ValueError(f"Figure not found: {figure_id}")


def _iter_pages(text_content: str) -> list[tuple[int, str]]:
    matches = list(_PAGE_MARKER_RE.finditer(text_content))
    pages: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        page = int(match.group(1))
        start = match.end()
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(text_content)
        )
        pages.append((page, text_content[start:end].lstrip("\r\n").rstrip()))
    return pages


def _find_section(page: int, nodes: list[TocNode]) -> dict[str, object]:
    candidates = [
        node
        for node in flatten_nodes(nodes)
        if node.start_page <= page <= node.end_page
    ]
    if not candidates:
        return {}
    node = min(
        candidates,
        key=lambda item: (item.end_page - item.start_page, -item.level),
    )
    return {
        "node_id": node.node_id,
        "title": node.title,
        "breadcrumb": node.breadcrumb,
        "start_page": node.start_page,
        "end_page": node.end_page,
    }


def _clean_title(title: str) -> str:
    return " ".join(title.strip(" .\t\r\n").split())


def _extend_caption_title(text: str, match: re.Match[str]) -> str:
    title = _clean_title(match.group("title"))
    continuation = _next_caption_line(text[match.end() :])
    if continuation and _title_likely_continues(title, continuation):
        return _clean_title(f"{title} {continuation}")
    return title


def _next_caption_line(text_after_caption: str) -> str:
    for line in text_after_caption.splitlines():
        candidate = _clean_title(line)
        if candidate:
            return candidate
    return ""


def _title_likely_continues(title: str, continuation: str) -> bool:
    if not continuation:
        return False
    lowered = continuation.casefold()
    if re.match(r"^(?:\d+\s+of\s+\d+|document\s+id|autosar|specification)\b", lowered):
        return False
    if re.match(r"^(?:figure|fig\.|table)\s+\d", lowered):
        return False
    title_lowered = title.casefold()
    if title.count("(") > title.count(")"):
        return True
    if title_lowered.endswith(
        (
            " and",
            " for",
            " in",
            " of",
            " or",
            " the",
            " to",
            " with",
            " without",
        )
    ):
        return True
    return continuation[:1].islower()


def _build_snippet(
    text: str,
    start: int,
    end: int,
    *,
    context_chars: int,
) -> str:
    left = max(0, start - context_chars)
    right = min(len(text), end + context_chars)
    snippet = " ".join(text[left:right].split())
    if left > 0:
        snippet = f"...{snippet}"
    if right < len(text):
        snippet = f"{snippet}..."
    return snippet


def _extract_keywords(text: str, max_keywords: int = 24) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for match in _WORD_RE.finditer(text):
        word = match.group(0).strip("_")
        normalized = word.casefold()
        if normalized in _STOPWORDS or normalized in seen:
            continue
        seen.add(normalized)
        result.append(word)
        if len(result) >= max_keywords:
            break
    return result


def _figure_search_text(figure: dict[str, object]) -> str:
    keywords = figure.get("keywords", [])
    if not isinstance(keywords, list):
        keywords = []
    parts = [
        str(figure.get("id", "")),
        str(figure.get("number", "")),
        str(figure.get("title", "")),
        str(figure.get("snippet", "")),
        " ".join(str(item) for item in keywords),
    ]
    return " ".join(parts).casefold()


def _normalize_figure_lookup(value: str) -> str:
    normalized = value.casefold().strip()
    normalized = normalized.removeprefix("figure").strip()
    normalized = normalized.removeprefix("fig.").strip()
    normalized = normalized.removeprefix("fig").strip()
    return normalized.strip(" :.-")
