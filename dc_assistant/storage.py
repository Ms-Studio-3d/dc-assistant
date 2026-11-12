import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .naming import NamingRule


def now():
    return datetime.now(timezone.utc).isoformat()


def new_id():
    return uuid.uuid4().hex


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA foreign_keys=ON")
            self._initialize_schema()
        except Exception:
            self.db.close()
            raise

    def _initialize_schema(self):
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            raise ValueError(
                "قاعدة البيانات من إصدار أحدث؛ افتحها بإصدار البرنامج المناسب"
            )
        schema = """
        CREATE TABLE IF NOT EXISTS projects(
            id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT NOT NULL,
            settings TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS registers(
            project_id TEXT PRIMARY KEY REFERENCES projects(id), source TEXT NOT NULL,
            mapping TEXT NOT NULL, records TEXT NOT NULL, imported TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS batches(
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
            folder TEXT NOT NULL, created TEXT NOT NULL, settings TEXT NOT NULL,
            results TEXT NOT NULL);
        """
        expected = {
            "projects": {"id", "name", "code", "settings", "created", "updated"},
            "registers": {"project_id", "source", "mapping", "records", "imported"},
            "batches": {"id", "project_id", "folder", "created", "settings", "results"},
        }
        with self.db:
            self.db.execute("BEGIN")
            for statement in schema.split(";"):
                if statement.strip():
                    self.db.execute(statement)
            for table, columns in expected.items():
                actual = {
                    row["name"]
                    for row in self.db.execute(f"PRAGMA table_info({table})")
                }
                if not columns <= actual:
                    raise ValueError(f"بنية قاعدة البيانات غير متوافقة: {table}")
            # Version 1 has the same columns as 0.1; existing rows stay untouched.
            self.db.execute("PRAGMA user_version=1")

    def projects(self):
        return [
            self._project(row)
            for row in self.db.execute(
                "SELECT * FROM projects ORDER BY name COLLATE NOCASE"
            )
        ]

    @staticmethod
    def _project(row):
        return {**dict(row), "settings": json.loads(row["settings"])} if row else None

    def get_project(self, project_id):
        return self._project(
            self.db.execute(
                "SELECT * FROM projects WHERE id=?", (project_id,)
            ).fetchone()
        )

    def save_project(self, name, code, settings, project_id=None):
        if not name.strip():
            raise ValueError("اسم المشروع مطلوب")
        if settings.get("parts"):
            NamingRule(settings)  # Validate before storing.
        project_id = project_id or new_id()
        old = self.get_project(project_id)
        with self.db:
            self.db.execute(
                """INSERT INTO projects(id,name,code,settings,created,updated) VALUES(?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,code=excluded.code,
                settings=excluded.settings,updated=excluded.updated""",
                (
                    project_id,
                    name.strip(),
                    code,
                    json.dumps(settings, ensure_ascii=False),
                    old["created"] if old else now(),
                    now(),
                ),
            )
        return project_id

    def save_register(self, project_id, source, mapping, records):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO registers(project_id,source,mapping,records,imported) VALUES(?,?,?,?,?)",
                (
                    project_id,
                    str(source),
                    json.dumps(mapping, ensure_ascii=False),
                    json.dumps(records, ensure_ascii=False),
                    now(),
                ),
            )

    def get_register(self, project_id):
        row = self.db.execute(
            "SELECT * FROM registers WHERE project_id=?", (project_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            **dict(row),
            "mapping": json.loads(row["mapping"]),
            "records": json.loads(row["records"]),
        }

    def save_batch(self, project_id, folder, settings, results):
        batch_id = new_id()
        with self.db:
            self.db.execute(
                "INSERT INTO batches(id,project_id,folder,created,settings,results) VALUES(?,?,?,?,?,?)",
                (
                    batch_id,
                    project_id,
                    str(folder),
                    now(),
                    json.dumps(settings, ensure_ascii=False),
                    json.dumps(results, ensure_ascii=False),
                ),
            )
        return batch_id

    def batches(self, project_id):
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT id,folder,created FROM batches WHERE project_id=? ORDER BY created DESC",
                (project_id,),
            )
        ]

    def get_batch(self, project_id, batch_id):
        row = self.db.execute(
            "SELECT * FROM batches WHERE id=? AND project_id=?", (batch_id, project_id)
        ).fetchone()
        return (
            {
                **dict(row),
                "results": json.loads(row["results"]),
                "settings": json.loads(row["settings"]),
            }
            if row
            else None
        )

    def close(self):
        self.db.close()
