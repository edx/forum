"""Deletion command for a course data in mongodb."""

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from forum.migration_helpers import delete_course_data, get_all_course_ids
from forum.mongo import get_database


class Command(BaseCommand):
    """Deletion command for a course data in mongodb."""

    help = "Delete data from MongoDB for specific courses or all courses"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "courses", nargs="+", type=str, help="List of course IDs or `all`"
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Perform a dry run without actually deleting data",
        )

    def handle(self, *args: str, **options: dict[str, Any]) -> None:
        """Handle method for command."""
        db = get_database()

        courses: list[str] = list(options["courses"])
        dry_run: bool = bool(options["dry_run"])

        if dry_run:
            self.stdout.write(
                self.style.WARNING("Performing dry run. No data will be deleted.")
            )

        if "all" in courses:
            courses = get_all_course_ids(db)

        for course_id in courses:
            self.stdout.write(f"Deleting data for course: {course_id}")
            delete_course_data(db, course_id, dry_run, self.stdout)

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS("Dry run completed. No data was deleted.")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("Data deletion completed successfully")
            )
