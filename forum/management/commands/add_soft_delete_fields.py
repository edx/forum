"""
Management command to update existing threads and comments with soft delete fields.
"""

from django.core.management.base import BaseCommand
from pymongo import MongoClient
from django.conf import settings


class Command(BaseCommand):
    help = 'Add is_deleted field to existing threads and comments'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes',
        )

    def handle(self, *args, **options):
        # Get MongoDB connection settings
        mongodb_settings = getattr(settings, 'FORUM_MONGODB_SETTINGS', {
            'host': 'localhost',
            'port': 27017,
            'database': 'cs_comments_service'
        })
        
        client = MongoClient(
            host=mongodb_settings.get('host', 'localhost'),
            port=mongodb_settings.get('port', 27017)
        )
        
        db = client[mongodb_settings.get('database', 'cs_comments_service')]
        contents_collection = db['contents']
        
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write('DRY RUN MODE - No changes will be made')
        
        # Update threads that don't have is_deleted field
        thread_filter = {
            '_type': 'CommentThread',
            'is_deleted': {'$exists': False}
        }
        
        thread_count = contents_collection.count_documents(thread_filter)
        self.stdout.write(f'Found {thread_count} threads without is_deleted field')
        
        if not dry_run and thread_count > 0:
            result = contents_collection.update_many(
                thread_filter,
                {
                    '$set': {
                        'is_deleted': False,
                        'deleted_at': None,
                        'deleted_by': None
                    }
                }
            )
            self.stdout.write(f'Updated {result.modified_count} threads')
        
        # Update comments that don't have is_deleted field
        comment_filter = {
            '_type': 'Comment',
            'is_deleted': {'$exists': False}
        }
        
        comment_count = contents_collection.count_documents(comment_filter)
        self.stdout.write(f'Found {comment_count} comments without is_deleted field')
        
        if not dry_run and comment_count > 0:
            result = contents_collection.update_many(
                comment_filter,
                {
                    '$set': {
                        'is_deleted': False,  
                        'deleted_at': None,
                        'deleted_by': None
                    }
                }
            )
            self.stdout.write(f'Updated {result.modified_count} comments')
        
        if dry_run:
            self.stdout.write(f'Would update {thread_count + comment_count} total documents')
        else:
            self.stdout.write(f'Successfully updated existing posts with soft delete fields')
        
        client.close()