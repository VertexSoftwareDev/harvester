import csv
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from harvester.exporters import (
    CsvExporter,
    ExcelExporter,
    JsonExporter,
    JsonLinesExporter,
    columns_of,
    exporter_registry,
)
from harvester.item import Item

ITEMS: list[Item] = [
    {"title": "Çay & Simit", "price": 12.5, "tags": ["food", "turkish"]},
    {"title": "Bell\x07 pepper", "url": "https://shop.test/p/2", "meta": {"k": "v"}},
    {"title": "Nothing", "price": None},
]


def test_columns_are_union_in_first_seen_order() -> None:
    assert columns_of(ITEMS) == ["title", "price", "tags", "url", "meta"]


def test_registry_contains_builtins() -> None:
    assert {"csv", "json", "jsonl", "excel"} <= set(exporter_registry.names())


def test_csv(tmp_path: Path) -> None:
    path = tmp_path / "out.csv"
    CsvExporter().export(ITEMS, path)

    assert path.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM for Excel
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0] == {"title": "Çay & Simit", "price": "12.5", "tags": "food, turkish",
                       "url": "", "meta": ""}  # fmt: skip
    assert rows[1]["meta"] == '{"k": "v"}'
    assert rows[2]["price"] == ""


@pytest.mark.parametrize("exporter", [JsonExporter(), JsonLinesExporter()])
def test_json_formats_keep_unicode_and_structure(
    tmp_path: Path, exporter: JsonExporter | JsonLinesExporter
) -> None:
    path = tmp_path / f"out.{exporter.extension}"
    exporter.export(ITEMS, path)

    text = path.read_text(encoding="utf-8")
    assert "Çay" in text
    loaded = (
        json.loads(text)
        if exporter.extension == "json"
        else [json.loads(line) for line in text.splitlines()]
    )
    assert loaded == ITEMS


def test_excel(tmp_path: Path) -> None:
    path = tmp_path / "out.xlsx"
    ExcelExporter().export(ITEMS, path)

    sheet = load_workbook(path).active
    assert sheet is not None
    assert [c.value for c in sheet[1]] == ["title", "price", "tags", "url", "meta"]
    assert sheet["A1"].font.bold
    assert sheet.freeze_panes == "A2"
    assert sheet["C2"].value == "food, turkish"
    assert sheet["A3"].value == "Bell pepper"  # control character stripped
    assert sheet["D3"].hyperlink is not None
    assert sheet["D3"].hyperlink.target == "https://shop.test/p/2"


def test_excel_with_no_items(tmp_path: Path) -> None:
    path = tmp_path / "empty.xlsx"
    ExcelExporter().export([], path)
    assert path.exists()
