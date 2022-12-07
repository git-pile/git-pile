#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.7.0
  load common.bash

  create_simple_repo $BATS_FILE_TMPDIR/testrepo
}

setup() {
  git clone $BATS_FILE_TMPDIR/testrepo $BATS_TEST_TMPDIR/testrepo
  pushd "$BATS_TEST_TMPDIR/testrepo"
  git pile init
  git checkout -b internal
}

@test "genpatches-no-commits" {
  git pile genpatches

  series=$(cat "$(git config pile.dir)/series" | sed '/^#\|^$/d')
  [ "$series" = "" ]

  patches=($(find patches -name '*.patch'))
  [ ${#patches[@]} -eq 0 ]
}

@test "genpatches-1-commit" {
  echo "pile 1" > j.txt && git add j.txt && git commit -m "add j.txt"
  git pile genpatches
  patches=("$(find patches -name '*.patch')")
  [ "${#patches[@]}" = "1" ]
  [ "${patches[0]}" = "patches/0001-add-j.txt.patch" ]
}

@test "genpatches-range" {
  echo "pile 1" > j.txt && git add j.txt && git commit -m "add range.txt"
  git pile genpatches $(git pile baseline)..HEAD
  patches=("$(find patches -name '*.patch')")
  [ "${#patches[@]}" = "1" ]
  [ "${patches[0]}" = "patches/0001-add-range.txt.patch" ]
  grep -q 0001-add-range.txt.patch patches/series
}

@test "genpatches-and-commit" {
  msg="add new.txt"
  echo "pile 1" > j.txt && git add j.txt && git commit -m "add new.txt"
  rev0=$(git -C patches rev-parse HEAD)

  git pile genpatches -m "$msg"

  rev1=$(git -C patches rev-parse HEAD)
  [ "$(git -C patches rev-list --count $rev0..$rev1)" -eq 1 ]
  [ "$(git -C patches log -1 --format=%s)" = "$msg" ]
}
