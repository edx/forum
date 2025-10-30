"""
Null search backend for testing - disables search functionality
"""

class NullSearchBackend:
    """Null search backend that does nothing"""
    
    def index_document(self, *args, **kwargs):
        """Do nothing when indexing documents"""
        pass
    
    def update_document(self, *args, **kwargs):
        """Do nothing when updating documents"""
        pass
    
    def delete_document(self, *args, **kwargs):
        """Do nothing when deleting documents"""
        pass
    
    def search(self, *args, **kwargs):
        """Return empty search results"""
        return {
            'collection': [],
            'total_results': 0,
            'page': 1,
            'num_pages': 1
        }


class NullDocumentSearchBackend:
    """Null document search backend"""
    
    def index_document(self, *args, **kwargs):
        pass
    
    def update_document(self, *args, **kwargs):
        pass
    
    def delete_document(self, *args, **kwargs):
        pass


# Main backend class
class NullBackend:
    """Null backend for testing"""
    SEARCH_CLASS = NullSearchBackend
    DOCUMENT_SEARCH_CLASS = NullDocumentSearchBackend