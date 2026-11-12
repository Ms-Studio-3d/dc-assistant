"""Local database backups and a per-directory single-instance lock."""

from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import uuid


class InstanceLock:
    def __init__(self, data_dir):
        directory = Path(data_dir)
        directory.mkdir(parents=True, exist_ok=True)
        self.file = (directory / "dc-assistant.lock").open("a+b")
        self.locked = False
        try:
            self.file.seek(0, 2)
            if self.file.tell() == 0:
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.locked = True
        except OSError as exc:
            self.file.close()
            raise RuntimeError(
                "البرنامج مفتوح بالفعل لهذه البيانات. أغلق النسخة الأخرى أولًا."
            ) from exc

    def close(self):
        if self.file.closed:
            return
        try:
            if self.locked:
                self.file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        finally:
            self.file.close()
            self.locked = False


def readonly_connection(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def validate_connection(connection):
    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise ValueError("ملف النسخة الاحتياطية غير سليم")
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, 1):
        raise ValueError("النسخة الاحتياطية تحتاج إصدارًا أحدث من البرنامج")
    expected = {
        "projects": {"id", "name", "code", "settings", "created", "updated"},
        "registers": {"project_id", "source", "mapping", "records", "imported"},
        "batches": {"id", "project_id", "folder", "created", "settings", "results"},
    }
    for table, columns in expected.items():
        actual = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if not columns <= actual:
            raise ValueError("الملف ليس نسخة متوافقة من بيانات DC Assistant")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("النسخة تحتوي سجلات غير مرتبطة بمشروع صالح")
    for table, fields in (
        ("projects", ("settings",)),
        ("registers", ("mapping", "records")),
        ("batches", ("settings", "results")),
    ):
        for row in connection.execute(f"SELECT {','.join(fields)} FROM {table}"):
            for field, value in zip(fields, row):
                parsed = json.loads(value)
                expected_type = list if field == "records" else dict
                if not isinstance(parsed, expected_type):
                    raise ValueError("النسخة تحتوي بيانات مشروع غير متوافقة")
    return {
        "projects": connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
        "batches": connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0],
        "schema_version": version,
    }


def inspect_backup(path):
    with closing(readonly_connection(path)) as connection:
        return validate_connection(connection)


def backup_database(store, target):
    target = Path(target).resolve()
    if target == store.path.resolve() or (
        target.exists() and os.path.samefile(target, store.path)
    ):
        raise ValueError("اختر ملفًا مختلفًا عن قاعدة البيانات الحالية")
    if target.suffix.lower() not in {".sqlite3", ".db"}:
        raise ValueError("احفظ النسخة بامتداد sqlite3 أو db")
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = target.with_name(f".{target.name}-{uuid.uuid4().hex}.pending")
    try:
        with closing(sqlite3.connect(pending)) as destination:
            store.db.backup(destination)
            validate_connection(destination)
        pending.replace(target)
    finally:
        if pending.exists():
            pending.unlink()
    return target


def daily_backup(store):
    if not store.db.execute("SELECT 1 FROM projects LIMIT 1").fetchone():
        return None
    folder = store.path.parent / "backups"
    target = folder / f"auto-{datetime.now().date().isoformat()}.sqlite3"
    if target.exists():
        inspect_backup(target)
        return target
    return backup_database(store, target)


def restore_database(store, source):
    source = Path(source).resolve()
    if source == store.path.resolve() or (
        source.exists() and os.path.samefile(source, store.path)
    ):
        raise ValueError("اختر نسخة احتياطية مختلفة عن قاعدة البيانات الحالية")
    with closing(readonly_connection(source)) as connection:
        connection.execute("BEGIN")
        validate_connection(connection)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safety = (
            store.path.parent
            / "backups"
            / f"before-restore-{stamp}-{uuid.uuid4().hex[:8]}.sqlite3"
        )
        backup_database(store, safety)
        connection.backup(store.db)
    store._initialize_schema()
    return safety
