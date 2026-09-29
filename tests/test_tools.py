from jarvis.tools.defaults import build_default_registry


def test_registry_has_initial_tools():
    registry = build_default_registry()
    assert {"get_cpu_usage", "get_ram_usage", "get_system_information", "open_application"}.issubset(registry.names())


def test_cpu_tool_returns_percentage():
    result = build_default_registry().execute("get_cpu_usage", {})
    assert 0 <= result["percent"] <= 100


def test_ram_tool_returns_real_values():
    result = build_default_registry().execute("get_ram_usage", {})
    assert 0 <= result["percent"] <= 100
    assert result["total_gb"] > 0
    assert result["available_gb"] >= 0
