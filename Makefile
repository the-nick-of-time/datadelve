sources = $(wildcard datadelve/*.py)
tests = $(wildcard tests/*.py)
documentation = $(wildcard docs/*.rst) docs/conf.py

.PHONY: test coverage view-coverage clean build publish

version := $(shell poetry version --short)

dist/datadelve-$(version).tar.gz dist/datadelve-$(version)-py3-none-any.whl: .coverage docs/_build/html/index.html
	poetry build

docs/_build/html/index.html: $(documentation) $(sources)
	sphinx-build -b html "docs" "docs/_build/html"

.coverage: $(sources) $(tests) .coveragerc
	coverage run -m nose2 --verbose
	coverage report

htmlcov/index.html: .coverage
	coverage html
