from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace
import unittest
import uuid

from dc_assistant.core import Store
from dc_assistant.data_safety import (
    InstanceLock,
    backup_database,
    daily_backup,
    inspect_backup,
    restore_database,
)


class DataSafetyTests(unittest.TestCase):
    def setUp(self):
        self.scratch = Path.cwd() / ".test-tmp"
        self.scratch.mkdir(exist_ok=True)
        self.root = self.scratch / uuid.uuid4().hex
        self.root.mkdir()
        self.store = Store(self.root / "live.sqlite3")

    def tearDown(self):
        self.store.close()
        self.root.resolve().relative_to(self.scratch.resolve())
        shutil.rmtree(self.root)

    def test_second_instance_is_rejected_then_lock_can_be_reused(self):
        first = InstanceLock(self.root)
        try:
            with self.assertRaises(RuntimeError):
                InstanceLock(self.root)
        finally:
            first.close()
        second = InstanceLock(self.root)
        second.close()
        second.close()

    def test_backup_contains_project_register_and_history(self):
        project = self.store.save_project("Saved", "000075", {})
        self.store.save_register(
            project, "source.xlsx", {"sheet": "Data"}, [{"number": "DOC"}]
        )
        self.store.save_batch(project, "folder", {}, {"items": []})
        backup = backup_database(self.store, self.root / "copy.sqlite3")
        self.assertEqual(inspect_backup(backup)["projects"], 1)
        with closing(sqlite3.connect(backup)) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM registers").fetchone()[0], 1
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0], 1
            )

    def test_restore_keeps_pre_restore_backup_and_source_unchanged(self):
        self.store.save_project("Old", "00075", {})
        backup = backup_database(self.store, self.root / "copy.sqlite3")
        original = backup.read_bytes()
        self.store.save_project("New", "NEW", {})
        safety = restore_database(self.store, backup)
        self.assertEqual([p["name"] for p in self.store.projects()], ["Old"])
        self.assertEqual(inspect_backup(safety)["projects"], 2)
        self.assertEqual(backup.read_bytes(), original)
        self.store.save_project("After restore", "NEXT", {})

    def test_invalid_restore_leaves_live_data_untouched(self):
        self.store.save_project("Keep", "P", {})
        bad = self.root / "bad.sqlite3"
        bad.write_bytes(b"not a database")
        with self.assertRaises((ValueError, sqlite3.DatabaseError)):
            restore_database(self.store, bad)
        self.assertEqual(self.store.projects()[0]["name"], "Keep")
        self.assertFalse((self.root / "backups").exists())

    def test_future_schema_restore_is_rejected(self):
        self.store.save_project("Keep", "P", {})
        backup = backup_database(self.store, self.root / "future.sqlite3")
        with closing(sqlite3.connect(backup)) as connection:
            connection.execute("PRAGMA user_version=99")
            connection.commit()
        with self.assertRaises(ValueError):
            restore_database(self.store, backup)
        self.assertEqual(self.store.projects()[0]["name"], "Keep")

    def test_legacy_backup_is_not_rewritten_by_restore(self):
        self.store.save_project("Legacy", "000075", {})
        backup = backup_database(self.store, self.root / "legacy.sqlite3")
        with closing(sqlite3.connect(backup)) as connection:
            connection.execute("PRAGMA user_version=0")
            connection.commit()
        restore_database(self.store, backup)
        self.assertEqual(self.store.db.execute("PRAGMA user_version").fetchone()[0], 1)
        with closing(sqlite3.connect(backup)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)

    def test_same_database_is_rejected_as_backup_or_restore(self):
        with self.assertRaises(ValueError):
            backup_database(self.store, self.store.path)
        with self.assertRaises(ValueError):
            restore_database(self.store, self.store.path)

    def test_daily_backup_keeps_first_snapshot(self):
        self.store.save_project("First", "P", {})
        backup = daily_backup(self.store)
        before = backup.read_bytes()
        self.store.save_project("Second", "Q", {})
        self.assertEqual(daily_backup(self.store), backup)
        self.assertEqual(backup.read_bytes(), before)

    def test_failed_backup_preserves_existing_destination(self):
        target = self.root / "backup.sqlite3"
        target.write_bytes(b"previous backup")

        class BrokenConnection:
            def backup(self, destination):
                raise OSError("simulated failure")

        with self.assertRaises(OSError):
            backup_database(
                SimpleNamespace(path=self.store.path, db=BrokenConnection()), target
            )
        self.assertEqual(target.read_bytes(), b"previous backup")
        self.assertEqual(list(self.root.glob("*.pending")), [])


if __name__ == "__main__":
    unittest.main()
