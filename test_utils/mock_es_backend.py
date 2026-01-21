"""
Mock Elasticsearch Backend.
"""

from typing import Any
from forum.search.es import ElasticsearchIndexBackend, ElasticsearchDocumentBackend


class MockElasticsearchIndexBackend(ElasticsearchIndexBackend):
    """
    Mocked class for ElasticsearchIndexBackend to return dummy values.

    Since we are using fixtures for the search API in tests, these methods
    are overridden to provide mocked behavior without performing actual operations.
    """

    def rebuild_indices(
        self, batch_size: int = 500, extra_catchup_minutes: int = 5
    ) -> None:
        """Mock method for rebuilding Elasticsearch indices."""

    def create_indices(self) -> list[str]:
        """Mock method for creating Elasticsearch indices."""
        return []

    def delete_index(self, name: str) -> None:
        """Mock method for deleting an Elasticsearch index."""

    def delete_unused_indices(self) -> int:
        """Mock method for deleting unused Elasticsearch indices."""
        return 0

    def move_alias(
        self, alias_name: str, index_name: str, force_delete: bool = False
    ) -> None:
        """Mock method for moving Elasticsearch aliases."""

    def refresh_indices(self) -> None:
        """Mock method for refreshing Elasticsearch indices."""

    def initialize_indices(self, force_new_index: bool = False) -> None:
        """Mock method for initializing Elasticsearch indices."""

    def validate_indices(self) -> None:
        """Mock method for validating Elasticsearch indices."""


class MockElasticsearchDocumentBackend(ElasticsearchDocumentBackend):
    """
    Mocked class for ElasticsearchDocumentBackend to return dummy values.
    """

    def update_document(
        self, index_name: str, doc_id: str | int, update_data: dict[str, Any]
    ) -> None:
        """Mock method for updating a document in Elasticsearch."""

    def delete_document(self, index_name: str, doc_id: str | int) -> None:
        """Mock method for deleting a document from Elasticsearch."""

    def index_document(
        self, index_name: str, doc_id: str | int, document: dict[str, Any]
    ) -> None:
        """Mock method for indexing a document in Elasticsearch."""
