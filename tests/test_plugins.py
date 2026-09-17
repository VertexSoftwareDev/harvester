from collections.abc import Callable
from dataclasses import dataclass

import pytest

from harvester import plugins
from harvester.plugins import PluginNotFoundError, Registry


@dataclass
class FakeEntryPoint:
    name: str
    target: Callable[[], object]
    value: str = "fake.module:obj"

    def load(self) -> object:
        return self.target()


def test_register_and_get() -> None:
    registry: Registry[object] = Registry("number")
    registry.add("one", 1)

    @registry.register("double")
    def double() -> int:
        return 2

    assert registry.get("one") == 1
    assert registry.get("double") is double
    assert registry.names() == ["double", "one"]
    assert "one" in registry
    assert len(registry) == 2
    assert dict(registry) == {"double": double, "one": 1}


def test_duplicate_names_are_rejected_unless_replaced() -> None:
    registry: Registry[int] = Registry("number")
    registry.add("x", 1)
    with pytest.raises(ValueError, match="already registered"):
        registry.add("x", 2)
    registry.add("x", 2, replace=True)
    assert registry.get("x") == 2


def test_not_found_error_suggests_close_match() -> None:
    registry: Registry[int] = Registry("number")
    registry.add("excel", 1)
    with pytest.raises(PluginNotFoundError, match="Did you mean 'excel'"):
        registry.get("exel")


def test_entry_points_are_loaded_lazily_and_errors_isolated(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken() -> object:
        raise ImportError("missing dependency")

    calls: list[str] = []

    def fake_entry_points(*, group: str) -> list[FakeEntryPoint]:
        calls.append(group)
        return [
            FakeEntryPoint("sheets", lambda: "SheetsExporter"),
            FakeEntryPoint("builtin", lambda: "shadow"),
            FakeEntryPoint("broken", broken),
        ]

    monkeypatch.setattr(plugins, "entry_points", fake_entry_points)
    registry: Registry[str] = Registry("exporter", entry_point_group="harvester.exporters")
    registry.add("builtin", "original")
    assert calls == []

    assert registry.get("sheets") == "SheetsExporter"
    assert registry.get("builtin") == "original"
    assert "broken" not in registry
    assert "Failed to load exporter plugin 'broken'" in caplog.text

    registry.names()
    assert calls == ["harvester.exporters"]
