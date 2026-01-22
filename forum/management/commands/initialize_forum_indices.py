"""Management command for initialize forum indices"""

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand

from forum.search import get_index_search_backend


class Command(BaseCommand):
    """
    Django management command for the initialization of search indices.
    """

    help = "Initialize Elasticsearch indices, optionally forcing the creation of new indices."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """
        Adds command line arguments to the initialize_forum_indices command.

        Args:
            parser: The argument parser to which the --force argument is added.
        """
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force the creation of new indices even if they exist.",
        )

    def handle(self, *args: list[str], **kwargs: dict[str, Any]) -> None:
        """
        Handles the execution of the initialize_indices command.

        Initializes Elasticsearch indices. If the --force option is provided,
        it forces the creation of new indices even if they exist.

        Args:
            args: Additional arguments.
            kwargs: Command options.
        """
        search_backend = get_index_search_backend()
        force_new_index = bool(kwargs.get("force", False))
        search_backend.initialize_indices(force_new_index=force_new_index)
        self.stdout.write(self.style.SUCCESS("Forum indices initialized successfully."))
