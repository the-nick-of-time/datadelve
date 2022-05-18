# DataDelve
[![PyPI version](https://badge.fury.io/py/datadelve.svg)](https://badge.fury.io/py/datadelve)
[![Coverage Status](https://coveralls.io/repos/github/the-nick-of-time/datadelve/badge.svg?branch=master)](https://coveralls.io/github/the-nick-of-time/datadelve?branch=master)
[![Build Status](https://travis-ci.org/the-nick-of-time/datadelve.svg?branch=master)](https://travis-ci.org/the-nick-of-time/datadelve)

Working with complex nested data can be tedious. If you have to access any objects that are four layers deep in a JSON response from a web service, you quickly tire of writing square brackets.
Much better would be to have a simple way of accessing data through a simple syntax. 
[jsonpointer](https://tools.ietf.org/html/rfc6901) is a perfect match, it looks just like paths through a filesystem.
Applying this information to the data structures makes it easy and convenient.

## Usage

```python
from datadelve import DataDelver

data = ["your annoying data here"]
delver = DataDelver(data)
element = delver.get("/dict/keys/and/1/list/index")
subset = delver.cd("/particular/key/to/focus/on")
delver.set("/path/to/change", "new")
delver.delete("/bad")
```

## Support

This package grew around a series of JSON files, so that is the primary focus. It therefore
expects data structures with dicts and lists. As the implementation is turned over to
jsonpointer, it will work for anything that implements `__getitem__(str)` or that is registered
as a `collections.abc.Sequence` and implements `__getitem__(int)`.

Raw data, loaded from whatever source, is accepted. So are JSON files. These have the added
benefit of being flyweight instances, so all views on the same file reference the same object.
This way none of them can get out of sync and make writes indeterminate as to what updates have
actually been made. As YAML isn't in the standard library, I've split support for that into a
separate project: [datadelve_yaml](https://pypi.org/project/datadelve_yaml/). YAML files are
treated the same as JSON.