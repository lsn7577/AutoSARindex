"""Tooling surfaces for bound document inspection and MCP handoff."""

from autosarindex.tools.registry import AutosarTools, create_autosar_tools_server
from autosarindex.tools.vision import inspect_page

DatasheetTools = AutosarTools
create_datasheet_tools_server = create_autosar_tools_server

__all__ = [
    "AutosarTools",
    "DatasheetTools",
    "create_autosar_tools_server",
    "create_datasheet_tools_server",
    "inspect_page",
]
