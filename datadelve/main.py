import collections.abc
import enum
import json
import typing
from pathlib import Path
from typing import Dict, Any, Union, List, Hashable

import jsonpointer

from datadelve.exceptions import ReadonlyError, MergeError, PathError, InvalidFileError, \
    UnreadableFileError, DuplicateInChainError, InitializationConflict, IterationError

JsonValue = Union[int, float, str, None, Dict[str, 'JsonValue'], List['JsonValue']]

__all__ = ['Delver', 'DataDelver', 'JsonDelver', 'ChainedDelver', 'FindStrategy', 'JsonPath']


class Delver:
    """All classes in this package follow this interface."""

    def __eq__(self, other):
        return self.get('') == other.get('')

    def __iter__(self):
        return self.values()

    def get(self, path: str, default=None) -> Any:
        """Retrieve an element from the backing data structure.

        :param path: The JSON Path of the element desired.
        :param default: If no element exists at the path specified, return this
            instead.
        :return: The requested element.
        """
        raise NotImplementedError()

    def set(self, path: str, value: Any, parents=False) -> None:
        """Replace the value at the specified location with a new one.

        Invariant: for an instance ``i``, if ``i.set(path, value)`` is called,
            ``i.get(path)`` returns ``value``.

        :param parents: Create intermediate dicts if they don't exist already.
            Will not create lists.
        :param path: The JSON Path of the element to replace.
        :param value: The value to replace with.
        """
        raise NotImplementedError()

    def delete(self, path: str) -> None:
        """Remove the specified element from the data structure.

        Invariant: for an instance `i`, if `i.delete(path)` is called,
            `i.get(path)` returns nothing.

        :param path: The JSON Path of the element to remove.
        """
        raise NotImplementedError()

    def cd(self, path: str, readonly=False) -> 'Delver':
        """Focuses in on a particular section of the data structure.

        Inspired by "changing directory" in a file system, where subsequent
            accesses will treat the path you have navigated to as the new root
            for further lookups.

        :param path: The path to make the new base for lookups.
        :param readonly: Whether this new view on the data should restrict
            setting or deleting members.
        :return: A Delver that treats the given path as if it were prepended on
            all paths given to the other functions.
        """
        raise NotImplementedError()

    def values(self, path="") -> typing.Iterator['Delver']:
        """``cd`` into all objects at path, in sequence.

        :param path: The path of the substructure you want to iterate over. By
            default, uses the whole thing (path ``""``).
        :return: A sub-delver for each object in the structure indicated by
            path.
        """
        structure = self.get(path)
        if isinstance(structure, collections.abc.Sequence):
            for i, _ in enumerate(structure):
                yield self.cd(path + f"/{i}")
        elif isinstance(structure, collections.abc.Mapping):
            for k in structure:
                yield self.cd(path + f"/{k}")
        else:
            raise IterationError(f"Object of type {type(structure)} is not iterable")
    
    def items(self, path="") -> typing.Iterator['Delver']:
        structure = self.get(path)
        if isinstance(structure, collections.abc.Sequence):
            for i, _ in enumerate(structure):
                yield i, self.cd(path + f"/{i}")
        elif isinstance(structure, collections.abc.Mapping):
            for k in structure:
                yield k, self.cd(path + f"/{k}")
        else:
            raise IterationError(f"Object of type {type(structure)} is not iterable")


class DataDelver(Delver):
    """A Delver which handles any general-purpose python data structure.

    Anything that supports __getitem__ (that is, structure[key]-style access)
        will work here.

    :ivar readonly: Whether this view on the data allows set and delete or not.
    :cvar _cache: A singular cache of JSON pointers to simplify the runtime.
    """
    _sentinel = object()

    class JsonPointerCache:
        """A cache of the JSON Pointers which have been used.

        Avoids constructing a new pointer object every time since in practice
            the same path is used multiple times over the course of the
            instance's lifetime.
        """

        def __init__(self):
            self.cache = {}

        def __getitem__(self, key: str) -> jsonpointer.JsonPointer:
            """Creates a JSON Pointer for the given path

            :param key: The path desired.
            :return: The JsonPointer object from parsing that path.
            """
            if key not in self.cache:
                self.cache[key] = jsonpointer.JsonPointer(key)
            return self.cache[key]

    # Since the JSON pointers aren't tied to any particular data, they can be
    # used across instances
    _cache = JsonPointerCache()

    def __init__(self, data: Union[list, Dict[str, Any]], readonly=False):
        """Wraps any general python data structure to allow easy access.

        :param data: The data structure to wrap
        :param readonly: Whether this view should be readonly
        """
        self.data = data
        self.readonly = readonly

    def get(self, path: str, default=None):
        if self.data is self._sentinel and path == '':
            return default
        pointer = self._cache[path]
        return pointer.resolve(self.data, default)

    def delete(self, path):
        """Deletes the element at the given path.

        :param path: The path leading to the element to delete
        """
        if self.readonly:
            raise ReadonlyError('{} is readonly'.format(self.data))
        if path == '':
            self.data = self._sentinel
            return
        pointer = self._cache[path]
        try:
            subdoc, key = pointer.to_last(self.data)
            del subdoc[key]
        except (jsonpointer.JsonPointerException, KeyError) as e:
            m = 'Some of the path segments of {} are missing within {}'.format(path, self.data)
            raise PathError(m) from e

    def set(self, path, value, parents=False):
        if self.readonly:
            raise ReadonlyError('{} is readonly'.format(self.data))
        if path == '':
            self.data = value
            return
        pointer = self._cache[path]
        try:
            pointer.set(self.data, value)
        except jsonpointer.JsonPointerException as e:
            if not parents:
                m = 'Some of the path segments of {} are missing within {}'.format(path,
                                                                                   self.data)
                raise PathError(m) from e
            # walk through the path segments to find any missing ones
            doc = self.data
            for part in pointer.parts[:-1]:
                try:
                    doc = pointer.walk(doc, part)
                except jsonpointer.JsonPointerException:
                    doc[part] = {}
                    doc = doc[part]
            doc[pointer.parts[-1]] = value

    def cd(self, path, readonly=False):
        return ChildDelver(self, self.readonly or readonly, path)


class ChildDelver(Delver):
    def __init__(self, parent: Delver, readonly=False, basepath=''):
        self.parent = parent
        self.readonly = readonly
        self.basepath = basepath.rstrip('/')

    def get(self, path, default=None):
        return self.parent.get(self.basepath + path, default)

    def set(self, path, value, parents=False):
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
    """A Delver that reads a JSON file and represents it uniquely.

    The class remembers which files have been opened, and will return the first
    JsonDelver to wrap a particular file if that file is requested again. This
    includes symbolic links that resolve to the same real file. This means that
    you cannot have two distinct JsonDelvers that point at the same file which
    may get out of sync with each other.

    :ivar filename: The file it read from and will write to.
    """
    __EXTANT = {}

    @staticmethod
    def cache_key(path: Union[Path, str]) -> Hashable:
        try:
            realpath = Path(path).resolve(strict=True)
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
        """Creates a view on the data contained within the JSON file specified.

        :param filename: The path of the file to read.
        :param readonly: Whether this JsonDelver should enable setting,
            deleting, and saving back to the file system.
        """
        if hasattr(self, '_initialized'):
            if readonly ^ self.readonly:
                raise InitializationConflict("Tried to create a JsonDelver with a different "
                                             "readonly parameter, so it's unclear which you "
                                             "want")
            return
        self.filename = Path(filename)
        try:
            with self.filename.open('r') as f:
                data = self._load(f)
                super().__init__(data, readonly)
        except OSError as e:
            raise UnreadableFileError(str(self.filename) + ' could not be read') from e
        type(self).__EXTANT[type(self).cache_key(self.filename)] = self
        self._initialized = True

    def __repr__(self):
        return "<{} to {}>".format(type(self).__name__, self.filename)

    def __str__(self):
        return self.filename.name

    def _load(self, file):
        try:
            data = json.load(file, object_pairs_hook=collections.OrderedDict)
        except json.JSONDecodeError as e:
            raise InvalidFileError(str(self.filename) + ' is not valid JSON') from e
        return data

    def write(self):
        """Writes back the updated values to the source file.

        :raises ReadonlyError: If this Delver is marked readonly. If it is,
            then presumably no changes could have been made to the data anyway,
            but prevent it all the same.
        """
        if self.readonly:
            raise ReadonlyError("Trying to write a readonly file")
        with self.filename.open('w') as f:
            json.dump(self.data, f, indent=2)


class FindStrategy(enum.Enum):
    """Decide how to get values from a ChainedDelver.

    See ChainedDelver.get for explanations of how they work.
    """
    FIRST = 'first'
    MERGE = 'merge'
    COLLECT = 'collect'


class ChainedDelver(Delver):
    def __init__(self, *delvers: Delver):
        """Collects multiple Delvers to look through all of them in order.

        :param delvers: Delvers must come in order from least to most specific
        """
        unique = set()
        for delver in delvers:
            if id(delver) in unique:
                raise DuplicateInChainError(str(delver) + ' is a duplicate')
            unique.add(id(delver))
        self.searchpath = delvers

    def __eq__(self, other):
        """Check equality with another ChainedDelver.

        Or something else that has .get with a FindStrategy specifiable.
        """
        return (self.get('', strategy=FindStrategy.COLLECT)
                == other.get('', strategy=FindStrategy.COLLECT))

    def decreasing_specificity(self):
        """Iterate over the contained delvers from most to least specific.

        :return: Iterable in the proper order
        """
        return reversed(self.searchpath)

    def increasing_specificity(self):
        """Iterate over the contained delvers from least to most specific.

        :return: Iterable in the proper order
        """
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
        """Gets a value from one of the Delvers in the chain.

        The three strategies mean:

        FIRST
            Find the value in the most specific Delver it occurs in. This is
            the default because it matches the semantics of the other types of
            Delvers the most closely. If no Delver has the value, return
            default.

        COLLECT
            For every Delver, if it has a value at the path, add it to a list.
            If the value occurs in no Delvers, return default. The default
            value does not need to be a list.

        MERGE
            Find the value from the least specific Delver possible, then add to
            it the values found in the rest of the Delvers. This allows more
            specific values to override more general ones. If no delvers have
            the value, return default.

        :param path: The path to look at in each contained Delver.
        :param default: The value to return if none are found.
        :param strategy: The strategy used to find one or more values.
        :return: The value or values found, or default if none are found.
        """
        strategies = {
            FindStrategy.FIRST: self._first,
            FindStrategy.MERGE: self._merge,
            FindStrategy.COLLECT: self._collect,
        }
        return strategies[strategy](path, default)

    def set(self, path: str, value: Any, parents=False) -> None:
        """Replaces the value at the path within the most specific Delver.

        This ensures that subsequent ``.get`` calls with the path and the
        ``FIRST`` find strategy will find this new value.

        :param parents: Create intermediate objects if they don't exist already.
            Will not create lists.
        :param path: The path to replace.
        :param value: The value to replace the current one with.
        """
        most_specific = next(self.decreasing_specificity())
        most_specific.set(path, value)

    def delete(self, path: str) -> None:
        """Deletes the value at the path within all Delvers.

        This ensures that subsequent ``.get`` calls will not find it.

        If any of the Delvers are readonly, this will raise a ``ReadonlyError``
        and do nothing.

        :param path: The path to try to delete.
        :raises ReadonlyError: If any of the Delvers are readonly, raise and do
            nothing.
        """
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


class JsonPath:
    def __init__(self, *components: str):
        """Handles the JSONPointer escapes that are annoying to track yourself."""
        if len(components) == 0:
            self.components = []
        if len(components) == 1:
            self.components = components[0].split('/')[1:]
        if len(components) > 1:
            self.components = [jsonpointer.escape(c) for c in components]

    def __str__(self):
        return '/' + '/'.join(self.components)

    def append(self, component: str):
        self.components.append(jsonpointer.escape(component))

    def extend(self, component: Union[str, 'JsonPath', collections.abc.Sequence]):
        if isinstance(component, str):
            new = component.lstrip('/').split('/')
            self.components.extend(new)
        elif isinstance(component, JsonPath):
            self.components.extend(component.components)
        elif isinstance(component, collections.Sequence):
            self.components.extend([jsonpointer.escape(c) for c in component])
        else:
            raise TypeError("Concatenate a string or JsonPath onto a JsonPath")
    
    def copy(self):
        return JsonPath(*self.components)
