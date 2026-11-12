"""Checks run by the actual Windows executable, isolated from user projects."""

import json
from pathlib import Path
import sys
import traceback


def write_text_fixture(path, pages):
    """Create real PDF text without adding a PDF-generation runtime dependency."""
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    for lines in pages:
        page = writer.add_blank_page(800, 600)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
            }
        )
        commands = []
        for index, line in enumerate(lines):
            safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"BT /F1 12 Tf 20 {550 - index * 30} Td ({safe}) Tj ET")
        stream = DecodedStreamObject()
        stream.set_data("\n".join(commands).encode("cp1252"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    with Path(path).open("wb") as output:
        writer.write(output)


def self_test(report_path, data_dir, inputs_path=None):
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    checks = []
    samples = []
    try:
        import tkinter as tk
        import openpyxl
        from pdfminer.cmapdb import CMapDB
        from . import __version__
        from .storage import Store
        from .reports import write_xlsx
        from .pdf_checks import read_pdf_isolated
        from .dialogs import RegisterDialog

        data_dir = Path(data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        root = tk.Tk()
        root.withdraw()
        try:
            root.update_idletasks()
            broken = data_dir / "broken.xlsx"
            broken.write_bytes(b"not a workbook")
            children = tuple(root.winfo_children())
            try:
                RegisterDialog(root, broken)
            except Exception:
                pass
            else:
                raise AssertionError("Broken workbook was accepted")
            assert tuple(root.winfo_children()) == children
            assert root.grab_current() is None
        finally:
            root.destroy()
        checks.extend(["tkinter", "corrupt workbook leaves no modal window"])

        store = Store(data_dir / "self-test.sqlite3")
        try:
            project = store.save_project("Self test", "000075", {})
            assert store.get_project(project)["code"] == "000075"
            assert store.db.execute("PRAGMA user_version").fetchone()[0] == 1
        finally:
            store.close()
        checks.extend(["sqlite schema version", "project persistence"])

        workbook_path = data_dir / "self-test.xlsx"
        write_xlsx(
            workbook_path,
            {"Check": [["Code", "Status"], ["000075", "Approved with Comments"]]},
        )
        workbook = openpyxl.load_workbook(workbook_path)
        try:
            assert workbook.active["A2"].value == "000075"
            assert workbook.active["B2"].value == "Approved with Comments"
        finally:
            workbook.close()
        checks.append("xlsx literal export/import")

        fixture = data_dir / "text-fixture.pdf"
        expected = "P-ARC-AMN-001-00"
        write_text_fixture(
            fixture, [["Drawing No: " + expected, "Document Title: Real text fixture"]]
        )
        for reader in ("auto", "pypdf", "pdfminer"):
            result = read_pdf_isolated(fixture, {}, reader=reader)
            assert expected in result["text"]
            assert "Real text fixture" in result["text"]
            assert result["pages"] == 1
            checks.append("isolated actual PDF text: " + result["reader"])
        assert CMapDB.get_cmap("UniJIS-UTF16-H") is not None
        assert CMapDB.get_unicode_map("Adobe-Japan1") is not None
        checks.append("packaged pdfminer CMap resources")

        if inputs_path:
            inputs = json.loads(Path(inputs_path).read_text(encoding="utf-8"))
            for sample in inputs:
                result = read_pdf_isolated(
                    sample["path"],
                    {"pdf_timeout_seconds": 90},
                    reader=sample.get("reader", "auto"),
                )
                compact = "".join(result["text"].split())
                for value in sample["contains"]:
                    assert (
                        "".join(value.split()) in compact
                    ), f"Expected PDF text missing: {value}"
                samples.append(
                    {
                        "file": Path(sample["path"]).name,
                        "reader": result["reader"],
                        "pages": result["pages"],
                        "expected_text_read": True,
                    }
                )
        import pdfminer

        report = {
            "passed": True,
            "version": __version__,
            "checks": checks,
            "samples": samples,
            "runtime": {
                "frozen": bool(getattr(sys, "frozen", False)),
                "pdfminer_module": pdfminer.__file__,
            },
        }
        exit_code = 0
    except Exception:
        report = {
            "passed": False,
            "checks": checks,
            "samples": samples,
            "error": traceback.format_exc(),
        }
        exit_code = 1
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return exit_code
