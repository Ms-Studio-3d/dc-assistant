import shutil
import uuid
import unittest
from pathlib import Path

import openpyxl
from pypdf import PdfWriter

from dc_assistant.core import (
    NamingRule,
    Store,
    export_results,
    read_register,
    scan_batch,
    write_xlsx,
)


def settings(code="00075"):
    roles = [
        "literal",
        "project",
        "literal",
        "literal",
        "discipline",
        "literal",
        "area",
        "number",
        "revision",
    ]
    samples = ["1", code, "QEI", "EEL", "ARC", "SDW", "AMN", "00001", "00"]
    return {
        "separator": "-",
        "parts": [{"role": r, "sample": s} for r, s in zip(roles, samples)],
        "project_aliases": [],
        "optional_revision": True,
        "excluded_folders": [],
        "ignore_case": False,
    }


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.scratch = Path.cwd() / ".test-tmp"
        self.scratch.mkdir(exist_ok=True)
        self.root = self.scratch / uuid.uuid4().hex
        self.root.mkdir()

    def tearDown(self):
        self.root.resolve().relative_to(self.scratch.resolve())
        shutil.rmtree(self.root)

    def pdf(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        writer = PdfWriter()
        writer.add_blank_page(600, 400)
        with path.open("wb") as f:
            writer.write(f)

    def test_project_rules_keep_zeroes_and_require_explicit_alias(self):
        rule = NamingRule(settings())
        self.assertIsNotNone(rule.parse("1-00075-QEI-EEL-ARC-SDW-AMN-00001-00.pdf"))
        self.assertIsNone(rule.parse("1-000075-QEI-EEL-ARC-SDW-AMN-00001-00.pdf"))
        conf = settings()
        conf["project_aliases"] = ["000075"]
        alias = NamingRule(conf).parse("1-000075-QEI-EEL-ARC-SDW-AMN-00001-00.pdf")
        self.assertEqual(alias["key"], "1-00075-QEI-EEL-ARC-SDW-AMN-00001")
        self.assertIn("000075", alias["number"])

    def test_pdf_text_keeps_boundaries_and_normalizes_separator_spaces(self):
        rule = NamingRule(settings())
        found = rule.find_in_pdf_text(
            "SHEET: 1-00075-QEI-EEL-ARC-SDW-AMN-00001- 00\nScale 1:50"
        )
        self.assertEqual(found[0]["revision"], "00")
        self.assertEqual(rule.revision("1.0"), "01")

    def test_expected_code_split_across_cad_text_runs(self):
        rule = NamingRule(settings())
        parsed = rule.parse("1-00075-QEI-EEL-ARC-SDW-AMN-00010-00.pdf")
        text = "SHEET\n1-0007\n5-QEI-EEL-A\nRC-SDW-AMN-0001\n0- 00\nScale 1:50"
        self.assertTrue(rule.expected_in_pdf_text(text, parsed))
        self.assertFalse(
            rule.expected_in_pdf_text(text.replace("0- 00", "0- 01"), parsed)
        )

    def test_persistence_isolation_and_batch_rule_snapshot(self):
        db = self.root / "store.db"
        store = Store(db)
        a = store.save_project("A", "00075", settings())
        b = store.save_project("B", "000075", settings("000075"))
        store.save_register(a, "register.xlsx", {}, [{"number": "A"}])
        batch = store.save_batch(a, "folder", settings(), {"items": []})
        changed = settings()
        changed["excluded_folders"] = ["OLD"]
        store.save_project("A", "00075", changed, a)
        store.close()
        store = Store(db)
        self.assertEqual(len(store.projects()), 2)
        self.assertIsNone(store.get_register(b))
        self.assertIsNone(store.get_batch(b, batch))
        self.assertEqual(store.get_batch(a, batch)["settings"]["excluded_folders"], [])
        self.assertEqual(store.get_project(b)["code"], "000075")
        store.close()

    def test_revision_mismatch_not_treated_as_current_document_present(self):
        name = "1-00075-QEI-EEL-ARC-SDW-AMN-00001-00.pdf"
        self.pdf(self.root / name)
        records = [
            {
                "number": "1-00075-QEI-EEL-ARC-SDW-AMN-00001",
                "revision": "01",
                "title": "Title",
                "status": "A",
                "row": 2,
                "source": "log.xlsx",
            }
        ]
        result = scan_batch(self.root, settings(), records, check_pdf=False)
        self.assertIn("الإصدار يختلف عن اللوج المستورد", result["items"][0]["issues"])
        self.assertEqual(result["items"][0]["status"], "")
        self.assertEqual(len(result["register_not_in_batch"]), 1)

    def test_repeated_register_rows_not_silently_joined(self):
        self.pdf(self.root / "1-00075-QEI-EEL-ARC-SDW-AMN-00001-00.pdf")
        record = {
            "number": "1-00075-QEI-EEL-ARC-SDW-AMN-00001",
            "revision": "00",
            "title": "One",
            "status": "A",
            "row": 2,
            "source": "log.xlsx",
        }
        other = {**record, "row": 3, "title": "Two"}
        result = scan_batch(self.root, settings(), [record, other], check_pdf=False)
        self.assertEqual(result["items"][0]["title"], "")
        self.assertTrue(any("أكثر من سجل" in x for x in result["items"][0]["issues"]))

    def test_same_revision_content_conflict_and_explicit_archive_exclusion(self):
        name = "1-00075-QEI-EEL-ARC-SDW-AMN-00001-00.dwg"
        (self.root / name).write_bytes(b"current")
        (self.root / "OLD").mkdir()
        (self.root / "OLD" / name).write_bytes(b"different")
        result = scan_batch(self.root, settings(), check_pdf=False)
        self.assertEqual(result["summary"]["files"], 2)
        self.assertTrue(
            all(any("ملفات مختلفة" in x for x in r["issues"]) for r in result["items"])
        )
        conf = settings()
        conf["excluded_folders"] = ["OLD"]
        self.assertEqual(
            scan_batch(self.root, conf, check_pdf=False)["summary"]["files"], 1
        )

    def test_export_preserves_identifiers_and_does_not_create_formulas(self):
        path = self.root / "out.xlsx"
        write_xlsx(path, {"Test": [["Code", "Text"], ["000075", '=HYPERLINK("x")']]})
        wb = openpyxl.load_workbook(path, data_only=False)
        self.assertEqual(wb.active["A2"].value, "000075")
        self.assertEqual(wb.active["B2"].data_type, "s")
        self.assertEqual(wb.active.freeze_panes, "A2")
        wb.close()

    def test_register_header_mapping_and_empty_template_rows(self):
        path = self.root / "log.xlsx"
        write_xlsx(
            path,
            {
                "Register": [
                    ["Intro"],
                    ["NO", "NUMBER", "TITLE"],
                    [1, "DOC-001", "Title"],
                    [2, "", ""],
                ]
            },
        )
        rows, warnings = read_register(
            path, {"sheet": "Register", "header_row": 2, "number": 1, "title": 2}
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["row"], 3)
        self.assertFalse(warnings)

    def test_blank_pdf_requires_manual_reading_not_a_pass(self):
        self.pdf(self.root / "1-00075-QEI-EEL-ARC-SDW-AMN-00001-00.pdf")
        result = scan_batch(self.root, settings(), check_pdf=True)
        self.assertTrue(any("OCR" in x for x in result["items"][0]["issues"]))

    def test_separate_data_start_and_attachment_inventory(self):
        path = self.root / "log.xlsx"
        write_xlsx(
            path,
            {"Sheet": [["Code", "Title"], ["TEMPLATE", "Example"], ["REAL", "Actual"]]},
        )
        records, _ = read_register(
            path,
            {
                "sheet": "Sheet",
                "header_row": 1,
                "data_start_row": 3,
                "number": 0,
                "title": 1,
            },
        )
        self.assertEqual([r["number"] for r in records], ["REAL"])
        result = scan_batch(self.root, settings(), check_pdf=False)
        self.assertEqual(len(result["attachments"]), 1)
        self.assertFalse(result["items"])

    def test_export_cannot_overwrite_source_register(self):
        path = self.root / "source.xlsx"
        path.write_bytes(b"original")
        results = {"items": [], "register_sources": [str(path)]}
        with self.assertRaises(ValueError):
            export_results(path, {}, results)
        self.assertEqual(path.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
