"""Management command for rebuild forum indices"""

from argparse import ArgumentParser

from django.core.management.base import BaseCommand

from forum.search import get_index_search_backend
from forum.utils import get_int_value_from_collection


class Command(BaseCommand):
    """
    Django management command for rebuilding search indices from scratch.
    """

    help = "Rebuild Elasticsearch indices by creating new indices and reindexing data."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """
        Adds command line arguments to the rebuild_forum_indices command.

        Args:
            parser: The argument parser to which the --batch_size and --extra_catchup_minutes arguments are added.
        """
        parser.add_argument(
            "--batch_size",
            type=int,
            default=500,
            help="Number of documents to process in each batch.",
        )
        parser.add_argument(
            "--extra_catchup_minutes",
            type=int,
            default=5,
            help="Extra minutes to adjust the start time for catch-up.",
        )

    def handle(self, *args: list[str], **kwargs: dict[str, int]) -> None:
        """
        Handles the execution of the rebuild_indices command.

        Rebuilds Elasticsearch indices by creating new indices and reindexing data.
        Batch size and extra catch-up minutes can be specified.

        Args:
            args: Additional arguments.
            kwargs: Command options.
        """
        search_backend = get_index_search_backend()

        batch_size = get_int_value_from_collection(kwargs, "batch_size", 500)
        extra_catchup_minutes = get_int_value_from_collection(
            kwargs, "extra_catchup_minutes", 5
        )

        search_backend.rebuild_indices(
            batch_size=batch_size, extra_catchup_minutes=extra_catchup_minutes
        )
        self.stdout.write(self.style.SUCCESS("Forum indices rebuilt successfully."))
