sources = $(wildcard datadelve/*.py)
tests = $(wildcard tests/*.py)

.PHONY: test coverage view-coverage clean build publish


build: coverage
	poetry build

publish: build
	# assert that working tree is clean, otherwise the tag might go in the wrong place
	test -z "$$(git status --short)"
	git tag $$(poetry version -s)
	poetry publish

# Intentionally have no prerequisites; should be able to run tests even if nothing has changed
test:
	nose2 --verbose

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
