class DelverError(Exception):
    pass


class ReadonlyError(DelverError):
    pass


class PathError(DelverError, ValueError):
    pass


class InvalidFileError(DelverError):
    pass


class UnreadableFileError(DelverError, OSError):
    pass


class MergeError(DelverError, TypeError):
    pass


class DuplicateInChainError(DelverError, ValueError):
    pass
