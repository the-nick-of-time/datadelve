#!/usr/bin/env bash

set -o errexit -o pipefail

errcho() {
  echo >&2 "$@"
}

version="$(poetry version --short)"

if [ -n "$(git status --short)" ]; then
  errcho Working tree not clean, make a commit to get into a publishable state
  exit 1
fi

if git tag "$version"; then
  exit 0
else
  existing="$(git rev-parse "$version")"
  head="$(git rev-parse HEAD)"
  if [ "$existing" = "$head" ]; then
    # already tagged the current commit, maybe with an aborted publish run
    exit 0
  else
    errcho "$version" was already tagged on some other commit, bump the version or move that tag to the current commit
    exit 2
  fi
fi
