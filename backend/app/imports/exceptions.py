class UnsupportedFileType(Exception):
    """Raised when an upload's extension isn't one PR-2.1 commits to
    accepting (CSV, XLS, XLSX)."""

    def __init__(self, extension: str):
        self.extension = extension
        super().__init__(f"Unsupported file type: {extension or '(none)'}")


class UnsupportedEntityType(Exception):
    """Raised when an upload's entity_type isn't one the detection engine
    (app/imports/aliases.py: SUPPORTED_ENTITY_TYPES) knows how to map yet."""

    def __init__(self, entity_type: str):
        self.entity_type = entity_type
        super().__init__(f"Unsupported entity type: {entity_type or '(none)'}")


class FileTooLarge(Exception):
    """Raised when an object exceeds the size guard for synchronous,
    in-request detection (no background job queue exists yet)."""

    def __init__(self, size_bytes: int, limit_bytes: int):
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes
        super().__init__(f"File is {size_bytes} bytes, over the {limit_bytes}-byte detection limit")


class HeaderRowNotFound(Exception):
    """Raised when no candidate row scores high enough to be confidently
    the header row (PR-2.2) — the file needs a human to point at it."""


class InvalidHeaderRowIndex(Exception):
    """Raised when a manually-specified header row index is out of range
    for the file — should only happen if the client is out of sync with
    the preview rows it was actually shown."""

    def __init__(self, index: int, row_count: int):
        self.index = index
        self.row_count = row_count
        super().__init__(f"Header row index {index} is out of range (file has {row_count} preview rows)")


class InsufficientMapping(Exception):
    """Raised when a confirmed mapping doesn't include the minimum fields
    needed to calculate anything (sale_date, and unit_price or total_amount)."""


class InvalidFieldMapping(Exception):
    """Raised when a confirmed mapping's shape is wrong (missing/unknown
    canonical field keys) or names a column that isn't actually in the
    file — never trust a client-supplied column name past this check."""


class UploadNotReady(Exception):
    """Raised when detect-mapping or confirm-mapping is attempted on an
    Upload that hasn't finished the R2 upload step yet (status != "uploaded")."""

    def __init__(self, status: str):
        self.status = status
        super().__init__(f"Upload is not ready for mapping (status={status})")


class ImportRecordNotReady(Exception):
    """Raised when running an import is attempted before confirm-mapping
    has produced an Upload/ImportRecord pair in status "mapped"."""

    def __init__(self, status: str):
        self.status = status
        super().__init__(f"Import is not ready to run (status={status})")


class MappedColumnMissing(Exception):
    """Raised when a column the confirmed mapping refers to is no longer
    in the file at import time (e.g. the file changed after confirm-mapping)
    — the whole import fails before writing anything, never partially."""

    def __init__(self, column: str):
        self.column = column
        super().__init__(f"Mapped column '{column}' is missing from this file")


class ImportNotReversible(Exception):
    """Raised when undo is attempted on an ImportRecord that either never
    completed or has already been reversed."""

    def __init__(self, status: str, reversed_at) -> None:
        self.status = status
        self.reversed_at = reversed_at
        super().__init__(f"Import cannot be reversed (status={status}, reversed_at={reversed_at})")
