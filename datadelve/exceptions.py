class DelverError(Exception):
    pass


class ReadonlyError(DelverError):
    pass


class PathError(DelverError, ValueError):
    pass


class MissingFileError(DelverError):
    pass


class MergeError(DelverError, TypeError):
    pass


class IterationError(DelverError, TypeError):
    pass
