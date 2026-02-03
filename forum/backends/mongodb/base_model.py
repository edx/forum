"""
Database models for forum.
"""

from abc import ABC
from typing import Any, Optional

from bson import ObjectId
from pymongo.collection import Collection as PymongoCollection
from pymongo.command_cursor import CommandCursor
from pymongo.cursor import Cursor

from forum.mongo import Database, get_database

Collection = PymongoCollection[dict[str, Any]]


class MongoBaseModel(ABC):
    """Abstract Class for Mongo model implementation"""

    MONGODB_DATABASE: Optional[Database] = None
    COLLECTION_NAME: str = "default"
    index_name: str = "default"

    @property
    def _collection(self) -> Collection:
        """Return the MongoDB collection for the model."""
        return self.__get_database()[self.COLLECTION_NAME]

    @classmethod
    def __get_database(cls) -> Database:
        """Get or create static class database."""
        if cls.MONGODB_DATABASE is None:
            cls.MONGODB_DATABASE = get_database()
        return cls.MONGODB_DATABASE

    def override_query(self, query: dict[str, Any]) -> dict[str, Any]:
        """Override Query"""
        return query

    def get(self, _id: str) -> Optional[dict[str, Any]]:
        """Get a document by ID."""
        return self._collection.find_one({"_id": ObjectId(_id)})

    def get_list(self, **kwargs: Any) -> Cursor[dict[str, Any]]:
        """Get a list of all documents filtered by kwargs."""
        return self._collection.find(kwargs)

    def delete(self, _id: str) -> int:
        """
        Delete a document from the database based on the ID.

        Args:
            _id: The ID of the document.

        Returns:
            The number of documents deleted.
        """
        result = self._collection.delete_one({"_id": ObjectId(_id)})
        return result.deleted_count

    def find(self, query: dict[str, Any]) -> Cursor[dict[str, Any]]:
        """
        Run a raw MongoDB query.

        Args:
            query: The MongoDB query.

        Returns:
            A cursor with the query results.
        """
        query = self.override_query(query)
        return self._collection.find(query)

    def find_one(self, query: dict[str, Any]) -> Optional[dict[str, Any]]:
        """
        Run a raw MongoDB query to find a single document.

        Args:
            query: The MongoDB query.

        Returns:
            The first document matching the query, or None if no document matches.
        """
        query = self.override_query(query)
        return self._collection.find_one(query)

    def aggregate(
        self, pipeline: list[dict[str, Any]]
    ) -> CommandCursor[dict[str, Any]]:
        """
        Run a MongoDB aggregation pipeline.

        Args:
            pipeline: The aggregation pipeline.

        Returns:
            A command cursor with the aggregation results.
        """
        return self._collection.aggregate(pipeline)

    def count_documents(self, query: dict[str, Any]) -> int:
        """
        Count the number of documents matching a query.

        Args:
            query: The MongoDB query.

        Returns:
            The count of documents matching the query.
        """
        query = self.override_query(query)
        return self._collection.count_documents(query)

    def distinct(self, field: str, query: dict[str, Any]) -> list[Any]:
        """
        Run a MongoDB distinct query.

        Args:
            field: The field for which to return distinct values.
            query: The MongoDB query.

        Returns:
            A list of distinct values for the specified field.
        """
        query = self.override_query(query)
        return self._collection.distinct(field, query)
