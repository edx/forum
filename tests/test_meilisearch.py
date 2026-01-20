"""
Unit tests for the meilisearch search backend.
"""

from unittest.mock import patch, Mock

import search.meilisearch as m
from forum.search import meilisearch

TEST_ID = "abcd"
TEST_PK = m.id2pk(TEST_ID)


def test_create_document() -> None:
    assert {
        "id": TEST_ID,
        m.PRIMARY_KEY_FIELD_NAME: TEST_PK,
    } == meilisearch.create_document({}, TEST_ID)

    assert {
        "id": TEST_ID,
        m.PRIMARY_KEY_FIELD_NAME: TEST_PK,
        "body": "Somebody",
    } == meilisearch.create_document({"body": "Somebody"}, TEST_ID)

    assert {
        "id": TEST_ID,
        m.PRIMARY_KEY_FIELD_NAME: TEST_PK,
        "course_id": "some/course/id",
    } == meilisearch.create_document({"course_id": "some/course/id"}, TEST_ID)

    assert {
        "id": TEST_ID,
        m.PRIMARY_KEY_FIELD_NAME: TEST_PK,
    } == meilisearch.create_document(
        {"field_should_not_be_here": "some_value"}, TEST_ID
    )

    assert {
        "id": TEST_ID,
        m.PRIMARY_KEY_FIELD_NAME: TEST_PK,
        "body": "Somebody",
    } == meilisearch.create_document({"body": "<p>Somebody</p>"}, TEST_ID)


def test_index_document() -> None:
    backend = meilisearch.MeilisearchDocumentBackend()
    with patch.object(
        backend, "get_index", return_value=Mock(add_documents=Mock())
    ) as mock_get_index:
        backend.index_document(
            "my_index",
            TEST_ID,
            {
                "body": "<p>Some body</p>",
                "some other field": "some value",
            },
        )
        mock_get_index.assert_called_once_with("my_index")
        mock_get_index().add_documents.assert_called_once_with(
            [
                {
                    "id": TEST_ID,
                    "_pk": TEST_PK,
                    "body": "Some body",
                }
            ]
        )


def test_delete_document() -> None:
    backend = meilisearch.MeilisearchDocumentBackend()
    with patch.object(
        backend, "get_index", return_value=Mock(add_documents=Mock())
    ) as mock_get_index:
        backend.delete_document("my_index", TEST_ID)
        mock_get_index.assert_called_once_with("my_index")
        mock_get_index().delete_document.assert_called_once_with(TEST_PK)
