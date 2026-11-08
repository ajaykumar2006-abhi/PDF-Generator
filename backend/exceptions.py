from __future__ import annotations


class AppError(Exception):
    def __init__(self, message: str, *, code: str = "app_error", status: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class DocumentError(AppError):
    def __init__(self, message: str, *, code: str = "document_error", status: int = 400):
        super().__init__(message, code=code, status=status)


class ExtractionWarning(Exception):
    """Non-fatal extraction warning attached to a document/page."""
    def __init__(self, message: str, *, page_number: int | None = None):
        super().__init__(message)
        self.message = message
        self.page_number = page_number


class ProviderUnavailable(AppError):
    def __init__(self, message: str = "No AI provider is configured"):
        super().__init__(message, code="provider_unavailable", status=503)


class RetrievalError(AppError):
    def __init__(self, message: str = "Retrieval failed"):
        super().__init__(message, code="retrieval_error", status=500)
