"""Migration command for courses from mongodb to mysql."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connections

import forum.migration_helpers as _migration_helpers
from forum.migration_helpers import (
    BATCH_SIZE,
    enable_mysql_backend_for_course,
    get_all_course_ids,
    migrate_content,
    migrate_read_states,
    migrate_users,
)
from forum.mongo import get_database

# ---------------------------------------------------------------------------
# Default parallelism.
# 1  = single-threaded (safe for SQLite / test environments, default).
# N  = N threads, each with its own Django DB connection; requires a
#      thread-safe database backend (MySQL, PostgreSQL) for N > 1.
# ---------------------------------------------------------------------------
DEFAULT_WORKERS = 1


def _migrate_one_course(
    course_id: str,
    create_waffle_flags: bool,
) -> tuple[str, float | None, str | None]:
    """
    Migrate a single course in the calling thread.

    Returns ``(course_id, elapsed_seconds, error_message_or_None)``.
    Each thread gets its own MongoDB client and Django DB connection.
    """
    # Django stores DB connections in thread-local storage, so each worker
    # thread automatically gets its own connection on first access.
    # Explicitly close any connection inherited from the spawning thread
    # so the worker starts with a clean slate.
    connections.close_all()

    db = get_database()
    t0 = time.monotonic()
    try:
        migrate_users(db, course_id)
        migrate_content(db, course_id)
        migrate_read_states(db, course_id)
        if create_waffle_flags:
            enable_mysql_backend_for_course(course_id)
        elapsed = time.monotonic() - t0
        return course_id, elapsed, None
    except Exception as exc:  # pylint: disable=broad-except
        elapsed = time.monotonic() - t0
        return course_id, elapsed, str(exc)
    finally:
        # Release the DB connection so the pool slot is returned promptly.
        connections.close_all()


class Command(BaseCommand):
    """Migration command for courses from mongodb to mysql."""

    help = "Migrate data from MongoDB to MySQL"

    def add_arguments(self, parser: CommandParser) -> None:
        """Add arguments to the command."""
        parser.add_argument(
            "-T",
            "--no-toggle",
            action="store_true",
            help="Skip course waffle flag creation",
        )
        parser.add_argument(
            "-w",
            "--workers",
            type=int,
            default=DEFAULT_WORKERS,
            metavar="N",
            help=(
                f"Number of parallel worker threads (default: {DEFAULT_WORKERS}). "
                "Each worker processes one course at a time and uses its own "
                "database connection.  Set > 1 only with a thread-safe DB "
                "backend (MySQL, PostgreSQL).  Example: --workers 8"
            ),
        )
        parser.add_argument(
            "-b",
            "--batch-size",
            type=int,
            default=BATCH_SIZE,
            metavar="N",
            help=f"Bulk-operation batch size (default: {BATCH_SIZE}).",
        )
        parser.add_argument(
            "courses", nargs="+", type=str, help="List of course IDs or `all`"
        )

    def handle(self, *args: str, **options: dict[str, Any]) -> None:
        """Handle the command."""
        db = get_database()

        create_waffle_flags = not options["no_toggle"]
        workers: int = int(str(options["workers"]))
        batch_size: int = int(str(options["batch_size"]))

        if workers < 1:
            raise CommandError("--workers must be >= 1.")
        if batch_size < 1:
            raise CommandError("--batch-size must be >= 1.")

        # Override module-level BATCH_SIZE when caller passes --batch-size.
        _migration_helpers.BATCH_SIZE = batch_size

        course_ids = list(options["courses"])
        if "all" in course_ids:
            course_ids = get_all_course_ids(db)

        total = len(course_ids)
        self.stdout.write(
            f"Migrating {total} course(s) with {workers} parallel worker(s) "
            f"(batch_size={_migration_helpers.BATCH_SIZE})."
        )

        failed: list[tuple[str, str]] = []
        completed = 0

        if workers == 1:
            # Single-threaded path: simpler, no executor overhead.
            for course_id in course_ids:
                cid, elapsed, err = _migrate_one_course(course_id, create_waffle_flags)
                completed += 1
                if err:
                    self.stderr.write(
                        self.style.ERROR(
                            f"[{completed}/{total}] FAILED {cid} after {elapsed:.1f}s: {err}"
                        )
                    )
                    failed.append((cid, err))
                else:
                    self.stdout.write(
                        f"[{completed}/{total}] OK {cid} ({elapsed:.1f}s)"
                    )
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(_migrate_one_course, cid, create_waffle_flags): cid
                    for cid in course_ids
                }
                for future in as_completed(futures):
                    cid, elapsed, err = future.result()
                    completed += 1
                    if err:
                        self.stderr.write(
                            self.style.ERROR(
                                f"[{completed}/{total}] FAILED {cid} after "
                                f"{elapsed:.1f}s: {err}"
                            )
                        )
                        failed.append((cid, err))
                    else:
                        self.stdout.write(
                            f"[{completed}/{total}] OK {cid} ({elapsed:.1f}s)"
                        )

        if failed:
            self.stderr.write(
                self.style.ERROR(f"\n{len(failed)} course(s) failed migration:")
            )
            for cid, err in failed:
                self.stderr.write(self.style.ERROR(f"  {cid}: {err}"))
            raise CommandError(
                f"{len(failed)} course(s) failed migration. See stderr for details."
            )

        self.stdout.write(self.style.SUCCESS("Data migration completed successfully"))
