import collections
import enum
import json
from pathlib import Path
from typing import Dict, Any, Union, List, Hashable

import jsonpointer
from datadelve.exceptions import ReadonlyError, MergeError, PathError, InvalidFileError, \
    UnreadableFileError, DuplicateInChainError

JsonValue = Union[int, float, str, None, Dict[str, 'JsonValue'], List['JsonValue']]


class Delver:
    def get(self, path: str, default=None) -> Any:
        raise NotImplementedError()

    def set(self, path: str, value: Any) -> None:
        raise NotImplementedError()

    def delete(self, path: str) -> None:
        raise NotImplementedError()

    def cd(self, path: str, readonly=False) -> 'Delver':
        raise NotImplementedError()


class DataDelver(Delver):
    class JsonPointerCache:
        def __init__(self):
            self.cache = {}

        def __getitem__(self, key: str) -> jsonpointer.JsonPointer:
            if key not in self.cache:
                self.cache[key] = jsonpointer.JsonPointer(key)
            return self.cache[key]

    def __init__(self, data: Union[list, Dict[str, Any]], readonly=False):
        self.data = data
        self.readonly = readonly
        self._cache = type(self).JsonPointerCache()

    def get(self, path: str, default=None):
        if path == '':
            return self.data
        pointer = self._cache[path]
        return pointer.resolve(self.data, default)

    def delete(self, path):
        if self.readonly:
            raise ReadonlyError('{} is readonly'.format(self.data))
        if path == '':
            self.data = {}
            return
        pointer = self._cache[path]
        try:
            subdoc, key = pointer.to_last(self.data)
            del subdoc[key]
        except (jsonpointer.JsonPointerException, KeyError) as e:
            m = 'Some of the path segments of {} are missing within {}'.format(path, self.data)
            raise PathError(m) from e

    def set(self, path, value):
        if self.readonly:
            raise ReadonlyError('{} is readonly'.format(self.data))
        if path == '':
            self.data = value
            return
        pointer = self._cache[path]
        try:
            pointer.set(self.data, value)
        except jsonpointer.JsonPointerException as e:
            m = 'Some of the path segments of {} are missing within {}'.format(path, self.data)
            raise PathError(m) from e

    def cd(self, path, readonly=False):
        return ChildDelver(self, self.readonly or readonly, path)


class ChildDelver(Delver):
    def __init__(self, parent: Delver, readonly=False, basepath=''):
        self.parent = parent
        self.readonly = readonly
        self.basepath = basepath.rstrip('/')

    def get(self, path, default=None):
        return self.parent.get(self.basepath + path, default)

    def set(self, path, value):
        if self.readonly:
            raise ReadonlyError('{} is readonly'.format(self))
        self.parent.set(self.basepath + path, value)

    def delete(self, path):
        if self.readonly:
            raise ReadonlyError('{} is readonly'.format(self))
        self.parent.delete(self.basepath + path)

    def cd(self, path, readonly=False):
        return ChildDelver(self.parent, self.readonly or readonly, self.basepath + path)


class JsonDelver(DataDelver):
    __EXTANT = {}

    @staticmethod
    def cache_key(path: Union[Path, str]) -> Hashable:
        try:
            realpath = Path(path).resolve()
        except OSError as e:
            raise UnreadableFileError(str(path) + ' could not be read') from e
        return str(realpath)

    def __new__(cls, path: Union[Path, str], **kwargs):
        key = cls.cache_key(path)
        if key in cls.__EXTANT:
            return cls.__EXTANT[key]
        else:
            obj = super().__new__(cls)
            return obj

    def __init__(self, filename: Union[Path, str], *, readonly=False):
        self.filename = Path(filename)
        try:
            with self.filename.open('r') as f:
                try:
                    data = json.load(f, object_pairs_hook=collections.OrderedDict)
                except json.JSONDecodeError as e:
                    raise InvalidFileError(str(self.filename) + ' is not valid JSON') from e
                super().__init__(data, readonly)
        except OSError as e:
            raise UnreadableFileError(str(self.filename) + ' could not be read') from e
        type(self).__EXTANT[str(self.filename)] = self

    def __repr__(self):
        return "<JsonDelver to {}>".format(self.filename)

    def __str__(self):
        return self.filename.name

    def write(self):
        if self.readonly:
            raise ReadonlyError("Trying to write a readonly file")
        with self.filename.open('w') as f:
            json.dump(self.data, f, indent=2)


class FindStrategy(enum.Enum):
    FIRST = 'first'
    MERGE = 'merge'
    COLLECT = 'collect'


class ChainedDelver(Delver):
    def __init__(self, *delvers: Delver):
        """Delvers should come in order from least to most specific"""
        unique = set()
        for delver in delvers:
            if delver in unique:
                raise DuplicateInChainError(str(delver) + ' is a duplicate')
            unique.add(delver)
        self.searchpath = delvers

    def decreasing_specificity(self):
        return reversed(self.searchpath)

    def increasing_specificity(self):
        return self.searchpath

    def _first(self, path: str, default=None):
        for delver in self.decreasing_specificity():
            found = delver.get(path)
            if found is not None:
                return found
        return default

    def _merge(self, path: str, default=None) -> Union[list, dict]:
        collected = None
        merger = None
        for delver in self.increasing_specificity():
            found = delver.get(path)
            if found is not None:
                if collected is None:
                    collected = found
                    if isinstance(found, dict):
                        merger = dict.update
                    elif isinstance(found, list):
                        merger = list.extend
                    else:
                        raise MergeError("Can only merge collections, not {!r}".format(found))
                else:
                    merger(collected, found)
        return collected if collected is not None else default

    def _collect(self, path: str, default=None) -> List[Any]:
        every = []
        for delver in self.decreasing_specificity():
            found = delver.get(path)
            if found is not None:
                every.append(found)
        return every if every != [] else default

    def get(self, path: str, default=None,
            strategy: FindStrategy = FindStrategy.FIRST) -> JsonValue:
        strategies = {
            FindStrategy.FIRST: self._first,
            FindStrategy.MERGE: self._merge,
            FindStrategy.COLLECT: self._collect,
        }
        return strategies[strategy](path, default)

    def set(self, path: str, value: Any) -> None:
        most_specific = next(self.decreasing_specificity())
        most_specific.set(path, value)

    def delete(self, path: str) -> None:
        if any((getattr(layer, 'readonly', False) for layer in self.decreasing_specificity())):
            raise ReadonlyError('Cannot delete {} from all delvers in {}'.format(
                path, list(self.increasing_specificity())
            ))
        for layer in self.increasing_specificity():
            try:
                layer.delete(path)
            except PathError:
                pass

    def cd(self, path: str, readonly=False) -> 'Delver':
        return ChildDelver(self, readonly, path)
