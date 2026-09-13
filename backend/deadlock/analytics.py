"""Identical relational detection queries run in the selected SQL engine."""
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from uuid import uuid4

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


class Analytics:
    def __init__(self, settings):
        self.kind = settings.database
        self.db = None
        self.available = False
        self.error = None
        self.last_success = None
        self.queries = []
        self.settings = settings
        self.connect()

    def connect(self):
        try:
            if self.kind == "sqlite":
                self.db = sqlite3.connect(self.settings.data_dir / "analytics.sqlite", check_same_thread=False)
                self.db.row_factory = sqlite3.Row
                self.db.execute("PRAGMA journal_mode=WAL")
            else:
                import pyexasol
                required = ["EXASOL_DSN", "EXASOL_USER", "EXASOL_PASSWORD"]
                if any(not os.getenv(k) for k in required):
                    raise ValueError("Configure EXASOL_DSN, EXASOL_USER, and EXASOL_PASSWORD")
                schema = os.getenv("EXASOL_SCHEMA", "DEADLOCK")
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", schema):
                    raise ValueError("Invalid Exasol schema name")
                self.db = pyexasol.connect(dsn=os.environ[required[0]], user=os.environ[required[1]],
                    password=os.environ[required[2]], autocommit=False, lower_ident=True,
                    connection_timeout=4, socket_timeout=5, query_timeout=5,
                    encryption=True, fetch_dict=True)
                self.db.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
                self.db.execute(f"OPEN SCHEMA {schema}")
            for statement in (SQL_DIR / "schema.sql").read_text().split(";"):
                if statement.strip():
                    self.db.execute(statement)
            self.db.commit()
            self.available, self.error = True, None
        except Exception as exc:
            # Do not serialize driver exceptions: they can contain connection credentials.
            self.available = False
            self.error = str(exc) if isinstance(exc, ValueError) else f"{self.kind} connection unavailable ({type(exc).__name__})"

    def execute(self, sql, params=None):
        if self.db is None:
            raise RuntimeError("Telemetry unavailable")
        if self.kind == "sqlite":
            return self.db.execute(re.sub(r"\{(\w+)\}", r":\1", sql), params or {})
        return self.db.execute(sql, params or {})

    def insert(self, table, columns, values):
        params = {f"v{i}": v for i, v in enumerate(values)}
        placeholders = ",".join("{" + k + "}" for k in params)
        self.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})", params)

    def snapshot(self, snap):
        if not self.available:
            return False
        sid, rid = snap["id"], snap["run_id"]
        try:
            self.insert("snapshots", ["id", "run_id", "captured", "complete"], [sid, rid, snap["captured"], 0])
            for w in snap["workers"]:
                self.insert("workers", ["snapshot_id", "run_id", "id", "attempt", "state", "progress", "stage_version", "checkpoint_id", "checkpoint_version", "checkpoint_work"],
                    [sid, rid, w["id"], w["attempt"], w["state"], w["progress"], w["version"], w["checkpoint_id"], w["checkpoint_version"], w["checkpoint_work"]])
                if w["waiting"]:
                    self.insert("waits", ["snapshot_id", "run_id", "worker_id", "resource_id", "version", "blocking"],
                        [sid, rid, w["id"], w["waiting"], w["request_version"], 1])
                for operation in w["capabilities"]:
                    yield_op = operation == "yield_and_resume"
                    eligible = not yield_op or bool(w["checkpoint_id"])
                    self.insert("capabilities", ["snapshot_id", "run_id", "worker_id", "operation", "eligible", "checkpoint_id", "lost_work", "version"],
                        [sid, rid, w["id"], operation, int(eligible), w["checkpoint_id"] if yield_op else None,
                         w["progress"] - (w["checkpoint_work"] if yield_op else 0), w["capability_version"]])
            for r in snap["resources"]:
                self.insert("resources", ["snapshot_id", "run_id", "id", "owner", "version", "capacity", "exclusive"],
                    [sid, rid, r["id"], r["owner"], r["version"], r["capacity"], int(r["exclusive"])])
            self.execute("UPDATE snapshots SET complete=1 WHERE id={sid} AND run_id={rid}", {"sid": sid, "rid": rid})
            self.db.commit()
            self.last_success = time.time()
            return True
        except Exception as exc:
            self.db.rollback()
            self.available = False
            self.error = f"Snapshot persistence failed ({type(exc).__name__})"
            return False

    def query(self, filename, snap):
        sql = (SQL_DIR / filename).read_text()
        started = time.perf_counter()
        rows = [dict(r) for r in self.execute(sql, {"sid": snap["id"], "rid": snap["run_id"]}).fetchall()]
        self.queries.append({"file": filename, "engine": self.kind, "sql": sql, "snapshot_id": snap["id"],
                             "rows": rows, "duration_ms": round((time.perf_counter()-started)*1000, 3)})
        self.queries = self.queries[-30:]
        return rows

    def record(self, run_id, kind, payload):
        if not self.available:
            return False
        try:
            self.insert("evidence", ["id", "run_id", "kind", "created", "payload"],
                [str(uuid4()), run_id, kind, time.time(), json.dumps(payload)])
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            self.available = False
            self.error = "Evidence persistence failed"
            return False

    def status(self):
        return {"engine": self.kind, "available": self.available, "error": self.error, "last_success": self.last_success}
