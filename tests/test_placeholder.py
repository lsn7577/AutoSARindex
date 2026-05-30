"""Import smoke tests for the renamed package and compatibility layer."""


def test_autosarindex_import():
    import autosarindex

    assert hasattr(autosarindex, "AutosarIndex")
    assert hasattr(autosarindex, "AutosarTools")
    assert hasattr(autosarindex, "create_autosar_tools_server")


def test_datasheetindex_compat_import():
    import autosarindex
    import datasheetindex

    assert datasheetindex.DatasheetIndex is autosarindex.AutosarIndex
    assert datasheetindex.DatasheetTools is autosarindex.AutosarTools
    assert (
        datasheetindex.create_datasheet_tools_server
        is autosarindex.create_autosar_tools_server
    )


def test_tools_package_exports():
    from autosarindex import tools as autosar_tools
    from datasheetindex import tools as datasheet_tools

    assert hasattr(autosar_tools, "AutosarTools")
    assert hasattr(autosar_tools, "create_autosar_tools_server")
    assert hasattr(datasheet_tools, "DatasheetTools")
    assert hasattr(datasheet_tools, "create_datasheet_tools_server")
    assert hasattr(datasheet_tools, "inspect_page")
