"""Management command for deleting unused indices"""

from django.core.management.base import BaseCommand

from forum.search import get_index_search_backend


class Command(BaseCommand):
    """
    Django management command for the deletion of unused search indices.
    """

    help = (
        "Delete all Elasticsearch indices that are not the latest for each model type."
    )

    def handle(self, *args: list[str], **kwargs: dict[str, str]) -> None:
        """
        Handles the execution of the delete_unused_forum_indices command.

        This command deletes all Elasticsearch indices that are not the latest for each model type.
        """
        search_backend = get_index_search_backend()
        indices_deleted_count = search_backend.delete_unused_indices()
        self.stdout.write(
            self.style.SUCCESS(
                f"{indices_deleted_count} unused indices deleted successfully."
            )
        )
