"""Management command for validating forum mappings"""

from django.core.management.base import BaseCommand

from forum.search import get_index_search_backend


class Command(BaseCommand):
    """
    Django management command to check the validity of search indices.
    """

    help = "Validate Elasticsearch indices for correct mappings and properties."

    def handle(self, *args: list[str], **kwargs: dict[str, str]) -> None:
        """
        Handles the execution of the validate_forum_indices command.

        This command validates that the search indices have the correct mappings and properties.

        Raises:
            ValueError: If indices do not exist or if mappings/properties are missing or incorrect.
        """
        search_backend = get_index_search_backend()
        search_backend.validate_indices()
        self.stdout.write(self.style.SUCCESS("Forum indices validated successfully."))
