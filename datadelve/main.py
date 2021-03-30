import collections
import enum
import json
from pathlib import Path
from typing import Dict, Any, Union, List, Hashable

import jsonpointer

from datadelve.exceptions import IterationError, ReadonlyError, MergeError, PathError, \
    InvalidFileError, UnreadableFileError, DuplicateInChainError

JsonValue = Union[int, float, str, None, Dict[str, 'JsonValue'], List['JsonValue']]


class Delver:
    def __iter__(self):
        obj = self.get('')
        if isinstance(obj, dict):
            yield from obj.items()
        elif isinstance(obj, list):
            yield from obj
        else:
            raise IterationError('Cannot iterate over {!r}'.format(obj))

    def get(self, path: str) -> Any:
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

    def get(self, path: str):
        if path == '':
            return self.data
        pointer = self._cache[path]
        return pointer.resolve(self.data, None)

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

    def get(self, path):
        return self.parent.get(self.basepath + path)

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

    def __init__(self, filename: Union[Path, str], readonly=False):
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


class MergeStrategy(enum.Enum):
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
        self.searchpath = collections.OrderedDict(
            (id(delver), delver) for delver in delvers)

    def _most_to_least(self):
        return reversed(self.searchpath.values())

    def _least_to_most(self):
        return self.searchpath.values()

    def _first(self, path: str):
        for delver in self._most_to_least():
            found = delver.get(path)
            if found is not None:
                return found
        return None

    def _merge(self, path: str) -> Union[list, dict]:
        collected = None
        merger = None
        for delver in self._least_to_most():
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
        return collected

    def _collect(self, path: str) -> List[Any]:
        every = []
        for delver in self._most_to_least():
            found = delver.get(path)
            if found is not None:
                every.append(found)
        return every

    def get(self, path: str, strategy: MergeStrategy = MergeStrategy.FIRST) -> JsonValue:
        strategies = {
            MergeStrategy.FIRST: self._first,
            MergeStrategy.MERGE: self._merge,
            MergeStrategy.COLLECT: self._collect,
        }
        return strategies[strategy](path)

    def set(self, path: str, value: Any) -> None:
        most_specific = next(self._most_to_least())
        most_specific.set(path, value)

    def delete(self, path: str) -> None:
        if any((getattr(layer, 'readonly', False) for layer in self._most_to_least())):
            raise ReadonlyError('Cannot delete {} from all delvers in {}'.format(
                path, list(self._least_to_most())
            ))
        for layer in self._least_to_most():
            try:
                layer.delete(path)
            except PathError:
                pass

    def cd(self, path: str, readonly=False) -> 'Delver':
        return ChildDelver(self, readonly, path)
