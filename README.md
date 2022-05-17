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
