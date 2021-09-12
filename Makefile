sources = $(wildcard datadelve/*.py)
tests = $(wildcard tests/*.py)
documentation = $(wildcard docs/*.rst) docs/conf.py

.PHONY: test coverage view-coverage clean build publish


build: coverage
	poetry build

publish: build
	./tag.sh
	poetry publish

# Intentionally have no prerequisites; should be able to run tests even if nothing has changed
test:
	nose2 --verbose

docs: docs/_build/html/index.html
view-docs: docs/_build/html/index.html
	firefox $<

docs/_build/html/index.html: $(documentation) $(sources)
	sphinx-build -b html "docs" "docs/_build/html"

view-coverage: coverage
	firefox htmlcov/index.html

coverage: htmlcov/index.html

.coverage: $(sources) $(tests) .coveragerc
	coverage run -m nose2 --verbose
	coverage report

htmlcov/index.html: .coverage
	coverage html

clean:
	git clean -xdf -e '/venv' -e '/.idea'
