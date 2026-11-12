from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

from dc_assistant.app import App
from dc_assistant.dialogs import ProjectDialog, RegisterDialog
from dc_assistant.reports import write_xlsx


class DialogTests(unittest.TestCase):
    def setUp(self):
        self.scratch = Path.cwd() / ".test-tmp"
        self.scratch.mkdir(exist_ok=True)
        self.root = self.scratch / uuid.uuid4().hex
        self.root.mkdir()
        self.app = App(self.root, show=False)
        self.app.withdraw()

    def tearDown(self):
        self.app.close()
        self.root.resolve().relative_to(self.scratch.resolve())
        shutil.rmtree(self.root)

    def test_corrupt_workbook_leaves_no_window_or_grab(self):
        path = self.root / "broken.xlsx"
        path.write_bytes(b"not a workbook")
        before = self.app.winfo_children()
        with self.assertRaises(Exception):
            RegisterDialog(self.app, path)
        self.assertEqual(self.app.winfo_children(), before)
        self.assertIsNone(self.app.grab_current())

    def test_constructor_failure_destroys_partial_dialog(self):
        path = self.root / "log.xlsx"
        write_xlsx(path, {"Data": [["Number"], ["DOC-1"]]})
        before = self.app.winfo_children()
        with patch.object(
            RegisterDialog, "_build", side_effect=RuntimeError("test failure")
        ):
            with self.assertRaises(RuntimeError):
                RegisterDialog(self.app, path)
        self.assertEqual(self.app.winfo_children(), before)
        self.assertIsNone(self.app.grab_current())

    def test_project_edit_keeps_unrelated_settings(self):
        project_id = self.app.store.save_project(
            "Saved", "P", {"custom_setting": {"key": "keep"}}
        )
        project = self.app.store.get_project(project_id)
        dialog = ProjectDialog(self.app, project)
        dialog.withdraw()
        dialog.save()
        self.assertEqual(
            self.app.store.get_project(project_id)["settings"]["custom_setting"],
            {"key": "keep"},
        )

    def test_import_warnings_preserve_previously_saved_register(self):
        project_id = self.app.store.save_project("Saved", "P", {})
        self.app.open_project(project_id)
        self.app.store.save_register(
            project_id, "old.xlsx", {"sheet": "Old"}, [{"number": "OLD"}]
        )
        mapping = {"sheet": "Data", "header_row": 1, "number": 0}
        with (
            patch(
                "dc_assistant.app.filedialog.askopenfilename", return_value="bad.xlsx"
            ),
            patch("dc_assistant.app.RegisterDialog") as dialog,
            patch.object(self.app, "wait_window"),
            patch(
                "dc_assistant.app.read_register",
                return_value=([{"number": "PARTIAL"}], ["Missing formula cache"]),
            ),
            patch("dc_assistant.app.messagebox.showerror") as show_error,
        ):
            dialog.return_value.result = mapping
            self.app.import_register()
        self.assertEqual(
            self.app.store.get_register(project_id)["records"], [{"number": "OLD"}]
        )
        show_error.assert_called_once()

    def test_workspace_has_existing_actions_and_cancel_state(self):
        project_id = self.app.store.save_project("Saved", "P", {})
        self.app.open_project(project_id)
        self.assertEqual(len(self.app.action_buttons), 6)
        self.app.set_busy(True)
        self.app.cancel_scan()
        self.assertTrue(self.app.cancel_event.is_set())
        self.app.set_busy(False)
        self.assertIn("disabled", self.app.cancel_button.state())


if __name__ == "__main__":
    unittest.main()
