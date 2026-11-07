class IngestionError(Exception):
    """Message is user-safe; the worker stores it in documents.error."""
