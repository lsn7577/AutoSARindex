"""Compatibility API for the AUTOSAR-oriented document indexer."""

from autosarindex.batch import BatchResult, build_batch
from autosarindex.index import AutosarIndex
from autosarindex.mcp_server import create_local_mcp_server, run_mcp_server
from autosarindex.tools.registry import AutosarTools, create_autosar_tools_server

DatasheetIndex = AutosarIndex
DatasheetTools = AutosarTools
create_datasheet_tools_server = create_autosar_tools_server

__all__ = [
    "AutosarIndex",
    "AutosarTools",
    "BatchResult",
    "DatasheetIndex",
    "DatasheetTools",
    "build_batch",
    "create_autosar_tools_server",
    "create_datasheet_tools_server",
    "create_local_mcp_server",
    "run_mcp_server",
]
