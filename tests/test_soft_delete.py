/**
 * Tests for soft delete functionality
 */
import pytest
from datetime import datetime
from bson import ObjectId
from unittest.mock import Mock, patch

from forum.backends.mongodb.threads import CommentThread
from forum.api.threads import (
    soft_delete_thread,
    restore_thread,
    bulk_soft_delete_threads,
    bulk_restore_threads,
    get_deleted_threads,
)
from forum.utils import ForumV2RequestError


class TestSoftDeleteFunctionality:
    """Test class for soft delete functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.thread_id = str(ObjectId())
        self.user_id = "test_user_123"
        self.course_id = "course-v1:edX+DemoX+Demo_Course"
        self.sample_thread = {
            "_id": ObjectId(self.thread_id),
            "title": "Test Thread",
            "body": "Test thread body",
            "course_id": self.course_id,
            "author_id": self.user_id,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }

    @patch('forum.api.threads.get_backend')
    def test_soft_delete_thread_success(self, mock_get_backend):
        """Test successful soft delete of a thread."""
        mock_backend = Mock()
        mock_backend.validate_object.return_value = self.sample_thread
        mock_backend.soft_delete_thread.return_value = 1
        mock_get_backend.return_value.return_value = mock_backend

        # Mock the updated thread with soft delete fields
        updated_thread = {
            **self.sample_thread,
            "is_deleted": True,
            "deleted_at": datetime.now(),
            "deleted_by": self.user_id,
        }
        
        with patch('forum.api.threads.prepare_thread_api_response') as mock_prepare:
            mock_prepare.return_value = {"id": self.thread_id, "is_deleted": True}
            mock_backend.validate_object.side_effect = [self.sample_thread, updated_thread]
            
            result = soft_delete_thread(self.thread_id, self.user_id, self.course_id)
            
            assert result["is_deleted"] is True
            mock_backend.soft_delete_thread.assert_called_once_with(self.thread_id, self.user_id)

    @patch('forum.api.threads.get_backend')
    def test_soft_delete_thread_already_deleted(self, mock_get_backend):
        """Test soft delete of already deleted thread raises error."""
        mock_backend = Mock()
        deleted_thread = {**self.sample_thread, "is_deleted": True}
        mock_backend.validate_object.return_value = deleted_thread
        mock_get_backend.return_value.return_value = mock_backend

        with pytest.raises(ForumV2RequestError, match="already deleted"):
            soft_delete_thread(self.thread_id, self.user_id, self.course_id)

    @patch('forum.api.threads.get_backend')
    def test_restore_thread_success(self, mock_get_backend):
        """Test successful restore of a soft deleted thread."""
        mock_backend = Mock()
        deleted_thread = {
            **self.sample_thread,
            "is_deleted": True,
            "deleted_at": datetime.now(),
            "deleted_by": self.user_id,
        }
        mock_backend.validate_object.return_value = deleted_thread
        mock_backend.restore_thread.return_value = 1
        mock_get_backend.return_value.return_value = mock_backend

        with patch('forum.api.threads.prepare_thread_api_response') as mock_prepare:
            mock_prepare.return_value = {"id": self.thread_id, "is_deleted": False}
            mock_backend.validate_object.side_effect = [deleted_thread, self.sample_thread]
            
            result = restore_thread(self.thread_id, self.course_id)
            
            assert result["is_deleted"] is False
            mock_backend.restore_thread.assert_called_once_with(self.thread_id)

    @patch('forum.api.threads.get_backend')
    def test_restore_thread_not_deleted(self, mock_get_backend):
        """Test restore of non-deleted thread raises error."""
        mock_backend = Mock()
        mock_backend.validate_object.return_value = self.sample_thread
        mock_get_backend.return_value.return_value = mock_backend

        with pytest.raises(ForumV2RequestError, match="not deleted"):
            restore_thread(self.thread_id, self.course_id)

    @patch('forum.api.threads.get_backend')
    def test_bulk_soft_delete_threads_success(self, mock_get_backend):
        """Test successful bulk soft delete of threads."""
        thread_ids = [str(ObjectId()), str(ObjectId())]
        mock_backend = Mock()
        mock_backend.validate_object.return_value = self.sample_thread
        mock_backend.bulk_soft_delete_threads.return_value = 2
        mock_get_backend.return_value.return_value = mock_backend

        result = bulk_soft_delete_threads(thread_ids, self.user_id, self.course_id)
        
        assert result["success_count"] == 2
        assert result["processed_threads"] == thread_ids
        assert len(result["errors"]) == 0
        mock_backend.bulk_soft_delete_threads.assert_called_once_with(thread_ids, self.user_id)

    @patch('forum.api.threads.get_backend')
    def test_bulk_restore_threads_success(self, mock_get_backend):
        """Test successful bulk restore of threads."""
        thread_ids = [str(ObjectId()), str(ObjectId())]
        mock_backend = Mock()
        deleted_thread = {**self.sample_thread, "is_deleted": True}
        mock_backend.validate_object.return_value = deleted_thread
        mock_backend.bulk_restore_threads.return_value = 2
        mock_get_backend.return_value.return_value = mock_backend

        result = bulk_restore_threads(thread_ids, self.course_id)
        
        assert result["success_count"] == 2
        assert result["processed_threads"] == thread_ids
        assert len(result["errors"]) == 0
        mock_backend.bulk_restore_threads.assert_called_once_with(thread_ids)

    @patch('forum.api.threads.get_backend')
    def test_get_deleted_threads_success(self, mock_get_backend):
        """Test successful retrieval of deleted threads."""
        mock_backend = Mock()
        deleted_threads = [
            {**self.sample_thread, "is_deleted": True},
            {**self.sample_thread, "_id": ObjectId(), "is_deleted": True},
        ]
        mock_backend.get_deleted_list.return_value = iter(deleted_threads)
        mock_get_backend.return_value.return_value = mock_backend

        with patch('forum.api.threads.prepare_thread_api_response') as mock_prepare:
            mock_prepare.return_value = {"id": self.thread_id, "is_deleted": True}
            
            result = get_deleted_threads(self.course_id)
            
            assert result["count"] == 2
            assert len(result["threads"]) == 2
            mock_backend.get_deleted_list.assert_called_once()

    def test_comment_thread_soft_delete_methods(self):
        """Test CommentThread soft delete methods."""
        with patch('forum.backends.mongodb.threads.CommentThread._collection') as mock_collection:
            mock_collection.update_one.return_value.modified_count = 1
            mock_collection.find_one.return_value = self.sample_thread
            
            comment_thread = CommentThread()
            
            # Test soft delete
            result = comment_thread.soft_delete(self.thread_id, self.user_id)
            assert result == 1
            
            # Verify the update query
            update_call = mock_collection.update_one.call_args
            assert update_call[0][0]["_id"] == ObjectId(self.thread_id)
            assert update_call[0][1]["$set"]["is_deleted"] is True
            assert update_call[0][1]["$set"]["deleted_by"] == self.user_id

    def test_comment_thread_restore_methods(self):
        """Test CommentThread restore methods."""
        with patch('forum.backends.mongodb.threads.CommentThread._collection') as mock_collection:
            mock_collection.update_one.return_value.modified_count = 1
            mock_collection.find_one.return_value = self.sample_thread
            
            comment_thread = CommentThread()
            
            # Test restore
            result = comment_thread.restore(self.thread_id)
            assert result == 1
            
            # Verify the update query
            update_call = mock_collection.update_one.call_args
            assert update_call[0][0]["_id"] == ObjectId(self.thread_id)
            assert update_call[0][0]["is_deleted"] is True
            assert "$unset" in update_call[0][1]

    def test_get_list_with_soft_delete_filter(self):
        """Test get_list method with soft delete filtering."""
        from forum.backends.mongodb.contents import BaseContents
        
        with patch('forum.backends.mongodb.contents.BaseContents._collection') as mock_collection:
            mock_cursor = Mock()
            mock_collection.find.return_value = mock_cursor
            
            base_contents = BaseContents()
            
            # Test excluding deleted items (default)
            base_contents.get_list(course_id=self.course_id)
            find_call = mock_collection.find.call_args[0][0]
            assert find_call["is_deleted"] == {"$ne": True}
            
            # Test including deleted items
            base_contents.get_list(course_id=self.course_id, include_deleted=True)
            find_call = mock_collection.find.call_args[0][0]
            assert "is_deleted" not in find_call or find_call.get("include_deleted") is True

    def test_elasticsearch_mapping_includes_soft_delete_fields(self):
        """Test that Elasticsearch mapping includes soft delete fields."""
        mapping = CommentThread.mapping()
        
        assert "is_deleted" in mapping["properties"]
        assert mapping["properties"]["is_deleted"]["type"] == "boolean"
        assert "deleted_at" in mapping["properties"]
        assert mapping["properties"]["deleted_at"]["type"] == "date"
        assert "deleted_by" in mapping["properties"]
        assert mapping["properties"]["deleted_by"]["type"] == "keyword"

    def test_doc_to_hash_includes_soft_delete_fields(self):
        """Test that doc_to_hash includes soft delete fields."""
        thread_with_soft_delete = {
            **self.sample_thread,
            "is_deleted": True,
            "deleted_at": datetime.now(),
            "deleted_by": self.user_id,
        }
        
        result = CommentThread.doc_to_hash(thread_with_soft_delete)
        
        assert result["is_deleted"] is True
        assert result["deleted_at"] is not None
        assert result["deleted_by"] == self.user_id