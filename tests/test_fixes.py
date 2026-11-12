from contextlib import closing
import multiprocessing
from pathlib import Path
import shutil
import threading
import time
import unittest
from unittest.mock import patch
import uuid
import xml.etree.ElementTree as ET
import zipfile

import openpyxl

from dc_assistant.core import (
    NamingRule,
    Store,
    export_results,
    read_register,
    scan_batch,
    write_xlsx,
)
from dc_assistant.diagnostics import write_text_fixture
from dc_assistant.issues import format_status, pdf_check_label
from dc_assistant.pdf_checks import ScanCancelled, read_first_page, read_pdf_isolated
from dc_assistant.registers import excel_columns


def settings():
    return {
        "parts": [
            {"role": role, "sample": sample}
            for role, sample in zip(
                ("project", "discipline", "area", "number", "revision"),
                ("P", "ARC", "AMN", "001", "00"),
            )
        ],
        "separator": "-",
        "optional_revision": True,
        "project_aliases": [],
        "statuses": {"A": "Approved for this project"},
    }


def record(**changes):
    return {
        "number": "P-ARC-AMN-001",
        "revision": "00",
        "title": "Drawing title",
        "discipline": "ARC",
        "area": "AMN",
        "status": "A",
        "row": 2,
        "source": "log.xlsx",
        **changes,
    }


def codes(item):
    return {issue["code"] for issue in item["issue_details"]}


def sleeping_worker(output_path, path, fallback, reader):
    time.sleep(20)


class FixTests(unittest.TestCase):
    def setUp(self):
        self.scratch = Path.cwd() / ".test-tmp"
        self.scratch.mkdir(exist_ok=True)
        self.root = self.scratch / uuid.uuid4().hex
        self.root.mkdir()
        self.mapping = {"sheet": "Data", "header_row": 1, "number": 0, "title": 1}

    def tearDown(self):
        self.root.resolve().relative_to(self.scratch.resolve())
        shutil.rmtree(self.root)

    def workbook(self, rows):
        path = self.root / "register.xlsx"
        write_xlsx(path, {"Data": rows})
        return path

    def rewrite_sheet(self, path, edit):
        with zipfile.ZipFile(path) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        name = "xl/worksheets/sheet1.xml"
        xml = ET.fromstring(parts[name])
        edit(xml, ns)
        parts[name] = ET.tostring(xml, encoding="utf-8", xml_declaration=True)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in parts.items():
                archive.writestr(name, content)

    def scan_dwg(self, rows=(), configuration=None):
        (self.root / "P-ARC-AMN-001-00.dwg").write_bytes(b"fixture")
        return scan_batch(self.root, configuration or settings(), rows, check_pdf=False)

    def test_truncated_sheet_dimensions_do_not_drop_rows_or_columns(self):
        path = self.workbook([["Number", "Title"], ["DOC-1", "One"], ["DOC-2", "Two"]])

        def truncate(xml, ns):
            xml.insert(0, ET.Element("{" + ns["s"] + "}dimension", {"ref": "A1:A2"}))

        self.rewrite_sheet(path, truncate)
        rows, warnings = read_register(path, self.mapping)
        self.assertEqual(
            [(row["number"], row["title"]) for row in rows],
            [("DOC-1", "One"), ("DOC-2", "Two")],
        )
        self.assertFalse(warnings)
        self.assertEqual(excel_columns(path, "Data", 1), [(0, "Number"), (1, "Title")])

    def test_formula_identifier_without_cache_reports_exact_cell(self):
        path = self.root / "register.xlsx"
        workbook = openpyxl.Workbook()
        workbook.active.title = "Data"
        workbook.active.append(["Number", "Title"])
        workbook.active.append(["DOC-1", "One"])
        workbook.active.append(['="DOC-2"', "Two"])
        workbook.save(path)
        workbook.close()
        rows, warnings = read_register(path, self.mapping)
        self.assertEqual([row["number"] for row in rows], ["DOC-1"])
        self.assertTrue(any("Data!A3" in warning for warning in warnings))
        self.assertTrue(any("1" in warning for warning in warnings))

    def test_blank_formula_filled_templates_are_not_document_records(self):
        path = self.root / "register.xlsx"
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Data"
        sheet.append(["Number", "Title"])
        sheet.append(["DOC-1", "One"])
        sheet.append([None, '=IF(A3="","","Title")'])
        workbook.save(path)
        workbook.close()
        rows, warnings = read_register(path, self.mapping)
        self.assertEqual(len(rows), 1)
        self.assertFalse(warnings)

    def test_cached_empty_formula_is_valid_not_an_uncalculated_cell(self):
        path = self.workbook([["Number", "Title"], ["DOC-1", ""]])

        def cached_empty(xml, ns):
            cell = xml.find(".//s:c[@r='B2']", ns)
            cell.clear()
            cell.attrib.update({"r": "B2", "t": "str"})
            ET.SubElement(cell, "{" + ns["s"] + "}f").text = 'IF(1=1,"","Title")'
            ET.SubElement(cell, "{" + ns["s"] + "}v")

        self.rewrite_sheet(path, cached_empty)
        rows, warnings = read_register(path, self.mapping)
        self.assertEqual(rows[0]["title"], "")
        self.assertFalse(warnings)

    def test_numeric_ids_honor_explicit_zero_format_and_keep_text(self):
        path = self.root / "register.xlsx"
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Data"
        sheet.append(["Number", "Title"])
        sheet.append([1.0, "Numeric"])
        sheet.append([7, "Formatted"])
        sheet["A3"].number_format = "00000"
        sheet.append(["000075", "Text"])
        sheet.append(["1.0", "Literal text"])
        workbook.save(path)
        workbook.close()
        rows, warnings = read_register(path, self.mapping)
        self.assertEqual(
            [row["number"] for row in rows], ["1", "00007", "000075", "1.0"]
        )
        self.assertEqual(rows[1]["number_raw"], "7")
        self.assertFalse(warnings)

    def test_uncached_string_formula_without_value_element_is_reported(self):
        path = self.workbook([["Number", "Title"], ["DOC-1", "Title"]])

        def remove_cache(xml, ns):
            cell = xml.find(".//s:c[@r='B2']", ns)
            cell.clear()
            cell.attrib.update({"r": "B2", "t": "str"})
            ET.SubElement(cell, "{" + ns["s"] + "}f").text = '"Title"'

        self.rewrite_sheet(path, remove_cache)
        rows, warnings = read_register(path, self.mapping)
        self.assertEqual(rows, [])
        self.assertTrue(any("Data!B2" in warning for warning in warnings))

    def test_incompatible_schema_initialization_is_rolled_back(self):
        import sqlite3

        path = self.root / "store.sqlite3"
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE projects(id TEXT)")
            connection.commit()
        with self.assertRaises(ValueError):
            Store(path)
        with closing(sqlite3.connect(path)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertEqual(tables, {"projects"})
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)

    def test_excel_error_and_data_without_number_are_reported(self):
        path = self.workbook([["Number", "Title"], ["DOC-1", "One"], ["", "Orphan"]])
        rows, warnings = read_register(path, self.mapping)
        self.assertEqual(len(rows), 1)
        self.assertTrue(any("3" in warning for warning in warnings))
        workbook = openpyxl.load_workbook(path)
        workbook.active["A3"] = "#REF!"
        workbook.save(path)
        workbook.close()
        rows, warnings = read_register(path, self.mapping)
        self.assertEqual(len(rows), 1)
        self.assertTrue(any("خطأ Excel" in warning for warning in warnings))

    def test_invalid_header_has_message_and_releases_file(self):
        path = self.workbook([["Number", "Title"], ["DOC-1", "One"]])
        with self.assertRaisesRegex(ValueError, "999"):
            excel_columns(path, "Data", 999)
        renamed = path.with_name("renamed.xlsx")
        path.rename(renamed)
        self.assertTrue(renamed.exists())

    def test_invalid_mapping_is_rejected(self):
        path = self.workbook([["Number", "Title"], ["DOC-1", "One"]])
        for changes in ({"number": None}, {"number": -1}, {"data_start_row": 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                read_register(path, {**self.mapping, **changes})

    def test_status_meaning_is_project_specific_and_exported(self):
        result = self.scan_dwg([record()])
        item = result["items"][0]
        self.assertEqual(item["status"], "A")
        self.assertEqual(item["status_meaning"], "Approved for this project")
        other = settings()
        other["statuses"] = {"A": "Different project meaning"}
        other_item = self.scan_dwg([record()], other)["items"][0]
        self.assertEqual(other_item["status_meaning"], "Different project meaning")
        path = self.root / "report.xlsx"
        export_results(
            path, {"name": "Audit", "code": "P", "settings": settings()}, result
        )
        workbook = openpyxl.load_workbook(path)
        try:
            values = list(workbook["المطابقة"].values)
            row = dict(zip(values[0], values[1]))
            self.assertEqual(row["كود الحالة من اللوج"], "A")
            self.assertEqual(row["معنى الحالة"], "Approved for this project")
        finally:
            workbook.close()

    def test_unknown_status_is_not_given_an_assumed_meaning(self):
        item = self.scan_dwg([record(status="UR")])["items"][0]
        self.assertEqual(item["status"], "UR")
        self.assertEqual(item["status_meaning"], "")
        self.assertIn("STATUS_UNDEFINED", codes(item))

    def test_status_is_not_linked_when_either_revision_is_unknown(self):
        item = self.scan_dwg([record(revision="")])["items"][0]
        self.assertEqual(item["status"], "")
        self.assertEqual(item["register_status_raw"], "A")
        self.assertIn("STATUS_REVISION_UNSPECIFIED", codes(item))
        (self.root / "P-ARC-AMN-001-00.dwg").unlink()
        (self.root / "P-ARC-AMN-001.dwg").write_bytes(b"fixture")
        item = scan_batch(self.root, settings(), [record()], check_pdf=False)["items"][
            0
        ]
        self.assertEqual(item["status"], "")
        self.assertIn("STATUS_REVISION_UNSPECIFIED", codes(item))

    def test_discipline_and_area_conflicts_preserve_both_sources(self):
        item = self.scan_dwg([record(discipline="STR", area="OTHER")])["items"][0]
        self.assertEqual(
            (item["discipline"], item["register_discipline"]), ("ARC", "STR")
        )
        self.assertEqual((item["area"], item["register_area"]), ("AMN", "OTHER"))
        self.assertIn("REGISTER_DISCIPLINE_MISMATCH", codes(item))
        self.assertIn("REGISTER_AREA_MISMATCH", codes(item))

    def test_separator_in_project_alias_does_not_shift_part_indexes(self):
        configuration = settings()
        configuration["project_aliases"] = ["ALT-X"]
        rule = NamingRule(configuration)
        item = rule.parse("ALT-X-ARC-AMN-001-00.pdf")
        self.assertEqual(item["key"], "P-ARC-AMN-001")
        self.assertEqual(item["number"], "ALT-X-ARC-AMN-001")
        self.assertTrue(rule.expected_in_pdf_text("Drawing: P-ARC-AMN-001-00", item))
        self.assertTrue(
            rule.expected_in_pdf_text("Drawing: ALT-X-ARC-AMN-001-00", item)
        )

    def test_unicode_underscore_and_plus_are_supported_with_hyphen_separator(self):
        parsed = NamingRule(settings()).parse("P-معماري_أ-مبنى+1-001-00.pdf")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["area"], "مبنى+1")

    def test_ambiguous_project_alias_is_rejected_before_matching(self):
        configuration = settings()
        configuration["project_aliases"] = ["P-ARC"]
        with self.assertRaises(ValueError):
            NamingRule(configuration)

    def test_dot_separator_does_not_join_sentence_punctuation(self):
        configuration = settings()
        configuration["separator"] = "."
        rule = NamingRule(configuration)
        parsed = rule.parse("P.ARC.AMN.001.00.pdf")
        self.assertTrue(rule.expected_in_pdf_text("P.ARC.AMN.001.00", parsed))
        self.assertFalse(rule.expected_in_pdf_text("P. ARC. AMN. 001. 00", parsed))
        self.assertEqual(rule.find_in_pdf_text("P. ARC. AMN. 001. 00"), [])

    def test_reference_number_is_never_reported_as_verified_titleblock(self):
        path = self.root / "P-ARC-AMN-001-00.pdf"
        write_text_fixture(
            path, [["Drawing No: P-ARC-AMN-999-00", "Refer to P-ARC-AMN-001-00"]]
        )
        item = scan_batch(self.root, settings())["items"][0]
        self.assertTrue(item["pdf_text_hit"])
        self.assertFalse(item["pdf_verified"])
        self.assertEqual(item["pdf_check_state"], "unverified")
        self.assertIn("PDF_TITLEBLOCK_UNVERIFIED", codes(item))
        self.assertIn("PDF_MULTIPLE_IDENTIFIERS", codes(item))

    def test_pages_after_first_are_explicitly_unchecked(self):
        write_text_fixture(
            self.root / "P-ARC-AMN-001-00.pdf",
            [
                ["P-ARC-AMN-001-00"],
                ["P-ARC-AMN-999-00"],
            ],
        )
        item = scan_batch(self.root, settings())["items"][0]
        self.assertEqual(item["pdf_pages"], 2)
        self.assertIn("PDF_MULTIPAGE_UNCHECKED", codes(item))
        self.assertFalse(item["pdf_verified"])

    def test_real_text_and_fallback_return_expected_values(self):
        path = self.root / "text.pdf"
        write_text_fixture(path, [["P-ARC-AMN-001-00", "Fixture drawing title"]])
        self.assertIn("Fixture drawing title", read_first_page(path)["text"])
        with patch(
            "pypdf.PdfReader", side_effect=ValueError("simulated primary failure")
        ):
            result = read_first_page(path, reader="pypdf")
        self.assertEqual(result["reader"], "pdfminer")
        self.assertIn("P-ARC-AMN-001-00", result["text"])
        with patch("pypdf.PdfReader", side_effect=ValueError("primary failure")):
            with self.assertRaises(ValueError):
                read_first_page(path, fallback=False, reader="pypdf")

    def test_primary_reader_failure_and_empty_text_use_alternate_reader(self):
        path = self.root / "text.pdf"
        write_text_fixture(path, [["P-ARC-AMN-001-00"]])
        with patch(
            "dc_assistant.pdf_checks._read_pdfium",
            side_effect=RuntimeError("simulated native failure"),
        ):
            result = read_first_page(path)
        self.assertEqual(result["reader"], "pypdf")
        self.assertIn("P-ARC-AMN-001-00", result["text"])
        with patch(
            "dc_assistant.pdf_checks._read_pdfium",
            return_value={"text": "", "pages": 1, "reader": "pypdfium2"},
        ):
            self.assertEqual(read_first_page(path)["reader"], "pypdf")

    def test_timed_out_reader_is_terminated_without_child_leak(self):
        before = {process.pid for process in multiprocessing.active_children()}
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            read_pdf_isolated(
                "unused.pdf", {"pdf_timeout_seconds": 0.4}, worker=sleeping_worker
            )
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(
            {process.pid for process in multiprocessing.active_children()}, before
        )

    def test_cancel_terminates_running_reader(self):
        event = threading.Event()
        timer = threading.Timer(0.4, event.set)
        timer.start()
        before = {process.pid for process in multiprocessing.active_children()}
        try:
            with self.assertRaises(ScanCancelled):
                read_pdf_isolated("unused.pdf", {}, event, worker=sleeping_worker)
        finally:
            timer.cancel()
        self.assertEqual(
            {process.pid for process in multiprocessing.active_children()}, before
        )

    def test_unique_files_do_not_get_hashed(self):
        with patch("dc_assistant.scanning.digest") as checksum:
            self.scan_dwg()
        checksum.assert_not_called()

    def test_conflicting_revision_inside_register_number_is_not_linked(self):
        result = self.scan_dwg([record(number="P-ARC-AMN-001-00", revision="01")])
        self.assertEqual(result["items"][0]["status"], "")
        self.assertEqual(len(result["invalid_register"]), 1)
        self.assertIn("invalid_reason", result["invalid_register"][0])

    def test_failed_export_keeps_previous_file_and_removes_temporary_file(self):
        path = self.root / "report.xlsx"
        path.write_bytes(b"previous report")

        def fail_save(workbook, target):
            Path(target).write_bytes(b"partial file")
            raise OSError("simulated disk error")

        with patch.object(openpyxl.Workbook, "save", fail_save):
            with self.assertRaises(OSError):
                write_xlsx(path, {"Data": [["Number"], ["DOC-1"]]})
        self.assertEqual(path.read_bytes(), b"previous report")
        self.assertEqual(list(self.root.glob("*.tmp.xlsx")), [])

    def test_cancelled_scan_does_not_return_a_partial_result(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(ScanCancelled):
            scan_batch(self.root, settings(), cancel_event=event)

    def test_database_upgrade_keeps_old_rows_and_history(self):
        path = self.root / "store.sqlite3"
        store = Store(path)
        project = store.save_project("Old project", "000075", settings())
        batch = store.save_batch(
            project, "folder", settings(), {"items": [], "old": True}
        )
        store.db.execute("PRAGMA user_version=0")
        store.db.commit()
        store.close()
        store = Store(path)
        try:
            self.assertEqual(store.db.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(store.get_project(project)["code"], "000075")
            self.assertTrue(store.get_batch(project, batch)["results"]["old"])
        finally:
            store.close()

    def test_newer_database_version_is_rejected_without_downgrading(self):
        path = self.root / "store.sqlite3"
        store = Store(path)
        store.db.execute("PRAGMA user_version=99")
        store.db.commit()
        store.close()
        with self.assertRaises(ValueError):
            Store(path)
        import sqlite3

        with closing(sqlite3.connect(path)) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0], 99
            )

    def test_old_history_text_is_labeled_unverified(self):
        old = {"format": "PDF", "pdf_check": "Old text result", "status": "A"}
        self.assertIn("غير متحققة", pdf_check_label(old))
        self.assertIn("Approved for this project", format_status(old, settings()))


if __name__ == "__main__":
    unittest.main()
