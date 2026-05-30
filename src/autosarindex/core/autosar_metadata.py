"""AUTOSAR standard document metadata detection."""

from __future__ import annotations

import re
from dataclasses import dataclass

_DOCUMENT_ID_RE = re.compile(r"\b(AUTOSAR_[A-Za-z0-9_]+)\b")
_RELEASE_RE = re.compile(r"\bR\d{2}-\d{2}\b")
_VERSION_RE = re.compile(
    r"\b(?:Document\s+)?Version\s*[:\-]?\s*([0-9]+(?:\.[0-9]+){1,3})\b",
    re.IGNORECASE,
)
_STATUS_RE = re.compile(
    r"\b(?:Document\s+)?Status\s*[:\-]?\s*([A-Za-z][A-Za-z ]{1,40})\b",
    re.IGNORECASE,
)
_PLATFORM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Classic Platform", re.compile(r"\bClassic\s+Platform\b", re.IGNORECASE)),
    ("Adaptive Platform", re.compile(r"\bAdaptive\s+Platform\b", re.IGNORECASE)),
    ("Foundation", re.compile(r"\bFoundation\b", re.IGNORECASE)),
)


@dataclass(frozen=True)
class AutosarMetadata:
    """Detected metadata for an AUTOSAR standard document."""

    document_title: str = ""
    document_id: str = ""
    release: str = ""
    version: str = ""
    status: str = ""
    platform: str = ""

    def to_dict(self) -> dict[str, str]:
        """Serialize non-empty metadata fields."""
        result: dict[str, str] = {}
        if self.document_title:
            result["document_title"] = self.document_title
        if self.document_id:
            result["document_id"] = self.document_id
        if self.release:
            result["release"] = self.release
        if self.version:
            result["version"] = self.version
        if self.status:
            result["status"] = self.status
        if self.platform:
            result["platform"] = self.platform
        return result


def extract_autosar_metadata(text: str) -> AutosarMetadata:
    """Extract common AUTOSAR cover-page metadata from page-marked text."""
    sample = text[:12000]
    lines = [line.strip() for line in sample.splitlines() if line.strip()]
    return AutosarMetadata(
        document_title=_extract_title(lines),
        document_id=_first_match(_DOCUMENT_ID_RE, sample),
        release=_first_match(_RELEASE_RE, sample),
        version=_first_group(_VERSION_RE, sample),
        status=_clean_status(_first_group(_STATUS_RE, sample)),
        platform=_detect_platform(sample),
    )


def is_autosar_document(metadata: AutosarMetadata, text: str) -> bool:
    """Return whether the source looks like an AUTOSAR standard document."""
    if metadata.document_id:
        return True
    sample = text[:12000].casefold()
    return "autosar" in sample and (
        "specification" in sample or "requirements" in sample or bool(metadata.release)
    )


def _extract_title(lines: list[str]) -> str:
    for line in lines:
        if _looks_like_title(line):
            return line
    for index, line in enumerate(lines):
        if line.casefold() == "autosar" and index + 1 < len(lines):
            candidate = lines[index + 1]
            if _looks_like_title(candidate):
                return candidate
    return ""


def _looks_like_title(line: str) -> bool:
    lower = line.casefold()
    if lower.startswith(("specification of ", "requirements on ")):
        return True
    return lower.startswith("autosar ") and "specification" in lower


def _first_match(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    if not match:
        return ""
    return match.group(1) if match.groups() else match.group(0)


def _first_group(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _clean_status(value: str) -> str:
    if not value:
        return ""
    return " ".join(value.split())[:40]


def _detect_platform(text: str) -> str:
    for platform, pattern in _PLATFORM_PATTERNS:
        if pattern.search(text):
            return platform
    return ""
