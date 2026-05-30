"""Tests for AUTOSAR document metadata detection."""

from autosarindex.core.autosar_metadata import (
    extract_autosar_metadata,
    is_autosar_document,
)


def test_extract_autosar_metadata_from_cover_text():
    text = """
    AUTOSAR
    Specification of Communication
    AUTOSAR_SWS_COM
    Classic Platform
    Document Version 4.7.0
    Document Status Final
    R24-11
    """

    metadata = extract_autosar_metadata(text)

    assert metadata.document_title == "Specification of Communication"
    assert metadata.document_id == "AUTOSAR_SWS_COM"
    assert metadata.platform == "Classic Platform"
    assert metadata.version == "4.7.0"
    assert metadata.status == "Final"
    assert metadata.release == "R24-11"
    assert is_autosar_document(metadata, text) is True


def test_non_autosar_text_is_not_autosar():
    text = "Electrical Characteristics\nAbsolute Maximum Ratings"
    metadata = extract_autosar_metadata(text)

    assert metadata.to_dict() == {}
    assert is_autosar_document(metadata, text) is False
