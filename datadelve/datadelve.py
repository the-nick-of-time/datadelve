import collections
import json
from pathlib import Path
from typing import Dict, Any, Union

import jsonpointer


class DelverError(Exception):
    pass


class ReadonlyError(DelverError):
    pass


class PathError(DelverError, ValueError):
    pass


class MissingFileError(DelverError):
    pass


class DataDelver:
    class JsonPointerCache:
        def __init__(self):
            self.cache = {}

        def __getitem__(self, key: str) -> jsonpointer.JsonPointer:
            if key not in self.cache:
                self.cache[key] = jsonpointer.JsonPointer(key)
            return self.cache[key]

    def __init__(self, data: Union[list, Dict[str, Any]], readonly=False, basepath=""):
        self.data = data
        self.basepath = basepath.rstrip('/')
        self.readonly = readonly
        self._cache = type(self).JsonPointerCache()

    def __iter__(self):
        obj = self.get('')
        if isinstance(obj, dict):
            yield from obj.items()
        elif isinstance(obj, list):
            yield from obj

    def get(self, path: str):
        if self.basepath + path == '':
            return self.data
        pointer = self._cache[self.basepath + path]
        return pointer.resolve(self.data, None)

    def delete(self, path):
        if self.readonly:
            raise ReadonlyError('{} is readonly'.format(self.data))
        if self.basepath + path == '':
            self.data = {}
            return
        pointer = self._cache[self.basepath + path]
        subdoc, key = pointer.to_last(self.data)
        del subdoc[key]

    def set(self, path, value):
        if self.readonly:
            raise ReadonlyError('{} is readonly'.format(self.data))
        if self.basepath + path == '':
            self.data = value
            return
        pointer = self._cache[self.basepath + path]
        pointer.set(self.data, value)

    def cd(self, path, readonly=False):
        return DataDelver(self.data, readonly=self.readonly or readonly,
                          basepath=self.basepath + path)


class JsonDelver(DataDelver):
    __EXTANT = {}

    def __new__(cls, path: Union[Path, str], **kwargs):
        if str(path) in cls.__EXTANT:
            return cls.__EXTANT[str(path)]
        else:
            obj = super().__new__(cls)
            return obj

    def __init__(self, filename: Union[Path, str], readonly=False):
        self.filename = Path(filename)
        with self.filename.open('r') as f:
            data = json.load(f, object_pairs_hook=collections.OrderedDict)
            super().__init__(data, readonly)
        type(self).__EXTANT[str(self.filename)] = self

    def __add__(self, other):
        if isinstance(other, JsonDelver):
            return ChainedDelver(self, other)
        elif isinstance(other, ChainedDelver):
            return other.__add__(self)
        else:
            raise TypeError("You can only add a JsonDelver or a "
                            "ChainedDelver to a JsonDelver")

    def __repr__(self):
        return "<JsonDelver to {}>".format(self.filename)

    def __str__(self):
        return self.filename.name

    def write(self):
        if self.readonly:
            raise ReadonlyError("Trying to write a readonly file")
        with open(self.filename, 'w') as f:
            json.dump(self.data, f, indent=2)


class ChainedDelver:
    def __init__(self, *interfaces: JsonDelver):
        """interfaces should come in order from least to most specific"""
        self.searchpath = collections.OrderedDict(
            (str(inter.filename), inter) for inter in interfaces)

    def __add__(self, other):
        if isinstance(other, ChainedDelver):
            self.searchpath.update(other.searchpath)
            return self
        elif isinstance(other, JsonDelver):
            self.searchpath[str(other.filename)] = other
            return self
        else:
            raise TypeError("You can only add a JsonDelver or a "
                            "ChainedDelver to a ChainedDelver")

    def _most_to_least(self):
        return reversed(self.searchpath.values())

    def _least_to_most(self):
        return self.searchpath.values()

    def get(self, path: str):
        split = path.split(':', maxsplit=1)
        if len(split) == 1:
            filename = None
            path = split[0]
        elif len(split) == 2:
            filename = split[0]
            path = split[1]
        else:
            raise PathError("Format should be filename:/path")
        if filename in self.searchpath:
            return self.searchpath[filename].get(path)
        elif filename == '*':
            # Find all results in all files
            # Search in more general files then override with more specific
            rv = None
            for iface in self._least_to_most():
                found = iface.get(path)
                if found is not None:
                    if rv is None:
                        if isinstance(found, list):
                            add = list.extend
                            rv = found
                        elif isinstance(found, dict):
                            add = dict.update
                            rv = found
                        else:
                            # Aggregate individual values into a list
                            rv = [found]
                            add = list.append
                    else:
                        # noinspection PyUnboundLocalVariable
                        add(rv, found)
            return rv
        elif filename is None:
            # Find one result in the most specific file you can find it in
            for iface in self._most_to_least():
                rv = iface.get(path)
                if rv is not None:
                    return rv
            return None
        else:
            raise PathError('If you supply a filename, it must be one in this '
                            'ChainedDelver or "*"')
