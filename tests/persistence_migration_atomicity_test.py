"""Focused regression tests for atomic, serialized SQLite migrations.

Every database and synthetic migration in this module is created below the
operating-system temporary directory.  The checked-in database and released
migration SQL are read-only inputs and are never modified.

Run:
    .venv/Scripts/python.exe -m unittest tests.persistence_migration_atomicity_test
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

from server.datasets.dataset_recovery import DatasetRecoveryService
from server.persistence import db as persistence_db
from server.persistence.db import Database, PersistenceUnavailableError
from tests.hermetic_test_roots import temporary_test_root


REAL_SCHEMA_PATH = persistence_db.SCHEMA_PATH
REAL_MIGRATIONS_PATH = persistence_db.MIGRATIONS_PATH
BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
);
"""


class MigrationAtomicityTest(unittest.TestCase):
    @contextmanager
    def synthetic_database(
        self,
        migrations: dict[str, str],
        *,
        schema: str = BASE_SCHEMA,
    ) -> Iterator[tuple[Database, Path]]:
        with temporary_test_root(
            "atlas-migration-atomicity-",
            scope="migration-atomicity-fixtures",
        ) as root:
            schema_path = root / "schema.sql"
            migration_root = root / "migrations"
            database_path = root / "atlas.db"
            migration_root.mkdir()
            schema_path.write_text(schema, encoding="utf-8")
            for name, sql in migrations.items():
                (migration_root / name).write_text(sql, encoding="utf-8")
            with (
                patch.object(persistence_db, "SCHEMA_PATH", schema_path),
                patch.object(persistence_db, "MIGRATIONS_PATH", migration_root),
            ):
                yield Database(database_path), database_path

    @staticmethod
    def object_names(database_path: Path) -> set[tuple[str, str]]:
        with closing(sqlite3.connect(database_path)) as connection:
            return {
                (row[0], row[1])
                for row in connection.execute(
                    """
                    SELECT type, name FROM sqlite_master
                    WHERE name NOT LIKE 'sqlite_%'
                    """
                ).fetchall()
            }

    @staticmethod
    def history(database_path: Path) -> list[str]:
        with closing(sqlite3.connect(database_path)) as connection:
            return [
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                ).fetchall()
            ]

    def assert_initialize_fails(self, database: Database) -> str:
        with self.assertRaises(PersistenceUnavailableError) as raised:
            database.initialize()
        return str(raised.exception)

    def test_table_creation_rolls_back_when_later_statement_fails(self) -> None:
        with self.synthetic_database(
            {
                "9000_table_failure.sql": """
                    CREATE TABLE leaked_table (id INTEGER PRIMARY KEY);
                    INSERT INTO missing_table (id) VALUES (1);
                """
            }
        ) as (database, path):
            failure = self.assert_initialize_fails(database)

            self.assertIn("9000_table_failure.sql", failure)
            self.assertNotIn(("table", "leaked_table"), self.object_names(path))
            self.assertEqual([], self.history(path))

    def test_added_column_rolls_back_when_later_statement_fails(self) -> None:
        schema = BASE_SCHEMA + "CREATE TABLE stable_table (id INTEGER PRIMARY KEY);"
        with self.synthetic_database(
            {
                "9001_column_failure.sql": """
                    ALTER TABLE stable_table ADD COLUMN leaked_column TEXT;
                    INSERT INTO missing_table (id) VALUES (1);
                """
            },
            schema=schema,
        ) as (database, path):
            self.assert_initialize_fails(database)

            with closing(sqlite3.connect(path)) as connection:
                columns = [
                    row[1]
                    for row in connection.execute("PRAGMA table_info(stable_table)").fetchall()
                ]
            self.assertEqual(["id"], columns)
            self.assertEqual([], self.history(path))

    def test_index_and_trigger_roll_back_when_later_statement_fails(self) -> None:
        schema = BASE_SCHEMA + "CREATE TABLE stable_table (id INTEGER PRIMARY KEY, value TEXT);"
        with self.synthetic_database(
            {
                "9002_object_failure.sql": """
                    CREATE INDEX leaked_index ON stable_table(value);
                    CREATE TRIGGER leaked_trigger AFTER INSERT ON stable_table
                    BEGIN
                      UPDATE stable_table SET value = 'triggered' WHERE id = NEW.id;
                    END;
                    INSERT INTO missing_table (id) VALUES (1);
                """
            },
            schema=schema,
        ) as (database, path):
            self.assert_initialize_fails(database)

            objects = self.object_names(path)
            self.assertNotIn(("index", "leaked_index"), objects)
            self.assertNotIn(("trigger", "leaked_trigger"), objects)
            self.assertEqual([], self.history(path))

    def test_data_changes_roll_back_when_later_statement_fails(self) -> None:
        schema = BASE_SCHEMA + """
            CREATE TABLE stable_table (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO stable_table (id, value) VALUES (1, 'original');
        """
        with self.synthetic_database(
            {
                "9003_data_failure.sql": """
                    UPDATE stable_table SET value = 'leaked' WHERE id = 1;
                    INSERT INTO missing_table (id) VALUES (1);
                """
            },
            schema=schema,
        ) as (database, path):
            self.assert_initialize_fails(database)

            with closing(sqlite3.connect(path)) as connection:
                value = connection.execute(
                    "SELECT value FROM stable_table WHERE id = 1"
                ).fetchone()[0]
            self.assertEqual("original", value)
            self.assertEqual([], self.history(path))

    def test_history_insert_failure_rolls_back_migration_side_effects(self) -> None:
        schema = BASE_SCHEMA + """
            CREATE TABLE stable_table (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO stable_table (id, value) VALUES (1, 'original');
            CREATE TRIGGER reject_test_history
            AFTER INSERT ON schema_migrations
            WHEN NEW.version = '9004_history_failure.sql'
            BEGIN
              SELECT RAISE(ABORT, 'intentional history failure');
            END;
        """
        with self.synthetic_database(
            {
                "9004_history_failure.sql": """
                    CREATE TABLE leaked_table (id INTEGER PRIMARY KEY);
                    UPDATE stable_table SET value = 'leaked' WHERE id = 1;
                """
            },
            schema=schema,
        ) as (database, path):
            failure = self.assert_initialize_fails(database)

            self.assertIn("intentional history failure", failure)
            self.assertNotIn(("table", "leaked_table"), self.object_names(path))
            with closing(sqlite3.connect(path)) as connection:
                value = connection.execute(
                    "SELECT value FROM stable_table WHERE id = 1"
                ).fetchone()[0]
            self.assertEqual("original", value)
            self.assertEqual([], self.history(path))

    def test_each_migration_is_an_independent_transaction(self) -> None:
        with self.synthetic_database(
            {
                "9005_first_success.sql": """
                    CREATE TABLE durable_table (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
                    INSERT INTO durable_table (id, value) VALUES (1, 'committed');
                """,
                "9006_second_failure.sql": """
                    UPDATE durable_table SET value = 'leaked' WHERE id = 1;
                    CREATE TABLE leaked_table (id INTEGER PRIMARY KEY);
                    INSERT INTO missing_table (id) VALUES (1);
                """,
            }
        ) as (database, path):
            self.assert_initialize_fails(database)

            self.assertEqual(["9005_first_success.sql"], self.history(path))
            self.assertNotIn(("table", "leaked_table"), self.object_names(path))
            with closing(sqlite3.connect(path)) as connection:
                value = connection.execute(
                    "SELECT value FROM durable_table WHERE id = 1"
                ).fetchone()[0]
            self.assertEqual("committed", value)

    def test_transaction_control_inside_migration_is_refused_and_rolled_back(self) -> None:
        with self.synthetic_database(
            {
                "9007_transaction_control.sql": """
                    CREATE TABLE leaked_table (id INTEGER PRIMARY KEY);
                    COMMIT;
                """
            }
        ) as (database, path):
            failure = self.assert_initialize_fails(database)

            self.assertIn("transaction-breaking top-level SQL (COMMIT)", failure)
            self.assertNotIn(("table", "leaked_table"), self.object_names(path))
            self.assertEqual([], self.history(path))

    def test_concurrent_runners_serialize_and_apply_once(self) -> None:
        with self.synthetic_database(
            {
                "9008_concurrent.sql": """
                    CREATE TABLE run_evidence (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
                    INSERT INTO run_evidence (id, value) VALUES (1, 'applied-once');
                """
            }
        ) as (_database, path):
            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(lambda _index: Database(path).initialize(), range(16)))

            self.assertTrue(all(result["ok"] for result in results))
            self.assertEqual(["9008_concurrent.sql"], self.history(path))
            with closing(sqlite3.connect(path)) as connection:
                row_count = connection.execute("SELECT count(1) FROM run_evidence").fetchone()[0]
            self.assertEqual(1, row_count)

    def test_spawned_startup_processes_apply_released_migrations_once(self) -> None:
        with temporary_test_root(
            "atlas-migration-concurrent-startup-",
            scope="migration-atomicity-fixtures",
        ) as root:
            database_path = root / "atlas.db"
            start_gate = root / "start-gate"
            expected_versions = [
                path.name for path in sorted(REAL_MIGRATIONS_PATH.glob("*.sql"))
            ]

            worker = Path(__file__).with_name("migration_startup_worker_subprocess.py")
            processes: list[tuple[subprocess.Popen[bytes], Path, object]] = []
            try:
                for index in range(4):
                    result_path = root / f"worker-{index}.json"
                    log_handle = (root / f"worker-{index}.log").open("wb")
                    process = subprocess.Popen(
                        [
                            sys.executable,
                            str(worker),
                            str(database_path),
                            str(start_gate),
                            str(result_path),
                        ],
                        cwd=Path(__file__).resolve().parents[1],
                        env=os.environ.copy(),
                        stdout=log_handle,
                        stderr=subprocess.STDOUT,
                    )
                    processes.append((process, result_path, log_handle))
                start_gate.write_text("start\n", encoding="utf-8")
                results = []
                for process, result_path, log_handle in processes:
                    return_code = process.wait(timeout=120.0)
                    log_handle.close()
                    self.assertEqual(0, return_code)
                    results.append(json.loads(result_path.read_text(encoding="utf-8")))
            finally:
                for process, _result_path, log_handle in processes:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=10.0)
                    if not log_handle.closed:
                        log_handle.close()

            for result in results:
                self.assertTrue(result["ok"])
                self.assertEqual(expected_versions, result["versions"])
                self.assertEqual(len(expected_versions), result["total"])
                self.assertEqual(result["total"], result["distinct"])
            self.assertEqual(expected_versions, self.history(database_path))

    def test_fresh_install_applies_every_released_migration(self) -> None:
        with temporary_test_root(
            "atlas-migration-fresh-install-",
            scope="migration-atomicity-fixtures",
        ) as root:
            database_path = root / "atlas.db"
            database = Database(database_path)

            result = database.initialize()

            self.assertTrue(result["ok"])
            expected_versions = [path.name for path in sorted(REAL_MIGRATIONS_PATH.glob("*.sql"))]
            self.assertEqual(expected_versions, self.history(database_path))
            objects = self.object_names(database_path)
            self.assertIn(("table", "projects"), objects)
            self.assertIn(("table", "analysis_partitions"), objects)
            self.assertIn(("table", "special_value_reviews"), objects)

    def test_representative_upgrade_applies_only_pending_migrations(self) -> None:
        with temporary_test_root(
            "atlas-migration-upgrade-",
            scope="migration-atomicity-fixtures",
        ) as root:
            database_path = root / "atlas.db"
            database = Database(database_path)
            released = sorted(REAL_MIGRATIONS_PATH.glob("*.sql"))
            pre_upgrade = released[:23]
            database._execute_script_atomically(
                REAL_SCHEMA_PATH.read_text(encoding="utf-8"),
                source=REAL_SCHEMA_PATH.name,
            )
            self.assertEqual([path.name for path in pre_upgrade], database.apply_migrations(pre_upgrade))

            database.initialize()

            self.assertEqual([path.name for path in released], self.history(database_path))
            objects = self.object_names(database_path)
            self.assertIn(("table", "analysis_partitions"), objects)
            self.assertIn(("table", "special_value_reviews"), objects)

    def test_dataset_recovery_applies_maintenance_files_through_canonical_runner(self) -> None:
        with temporary_test_root(
            "atlas-migration-recovery-path-",
            scope="migration-atomicity-fixtures",
        ) as root:
            database_path = root / "atlas.db"
            database = Database(database_path)
            released = sorted(REAL_MIGRATIONS_PATH.glob("*.sql"))
            database._execute_script_atomically(
                REAL_SCHEMA_PATH.read_text(encoding="utf-8"),
                source=REAL_SCHEMA_PATH.name,
            )
            database.apply_migrations(released[:21])
            service = DatasetRecoveryService(
                storage=object(),  # type: ignore[arg-type] - unused by this focused path
                security_database=root / "unused-security.db",
                persistence_database=database_path,
            )

            self.assertTrue(service._ensure_maintenance_schema())
            self.assertFalse(service._ensure_maintenance_schema())

            self.assertEqual(
                [path.name for path in released[:23]],
                self.history(database_path),
            )
            objects = self.object_names(database_path)
            self.assertIn(("table", "dataset_library_maintenance_events"), objects)
            self.assertIn(
                ("trigger", "trg_dataset_library_maintenance_events_no_update"),
                objects,
            )

    def test_idempotency_and_restart_do_not_reapply_migrations(self) -> None:
        with self.synthetic_database(
            {
                "9009_restart.sql": """
                    CREATE TABLE run_evidence (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
                    INSERT INTO run_evidence (id, value) VALUES (1, 'once');
                """
            }
        ) as (database, path):
            first = database.initialize()
            second = database.initialize()
            restarted = Database(path).initialize()

            self.assertTrue(first["ok"] and second["ok"] and restarted["ok"])
            self.assertEqual(["9009_restart.sql"], self.history(path))
            with closing(sqlite3.connect(path)) as connection:
                row_count = connection.execute("SELECT count(1) FROM run_evidence").fetchone()[0]
            self.assertEqual(1, row_count)

    def test_fastapi_startup_propagates_persistence_initialization_failure(self) -> None:
        from server import main

        startup = next(
            callback
            for callback in main.app.router.on_startup
            if callback.__name__ == "restore_session_checkpoint"
        )
        with (
            patch.object(main, "validate_security_configuration", return_value={"warnings": []}),
            patch.object(main, "init_security_store"),
            patch.object(main, "list_users", return_value=[]),
            patch.object(
                main,
                "initialize_persistence",
                side_effect=PersistenceUnavailableError("intentional migration failure"),
            ),
        ):
            with self.assertRaisesRegex(
                PersistenceUnavailableError,
                "intentional migration failure",
            ):
                startup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
