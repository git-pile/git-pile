#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.7.0
  load common.bash

  create_simple_repo $BATS_FILE_TMPDIR/testrepo
}

setup() {
  load common.bash
  git clone $BATS_FILE_TMPDIR/testrepo $BATS_TEST_TMPDIR/testrepo
  pushd "$BATS_TEST_TMPDIR/testrepo"
  git pile init
  git checkout -b internal
}

@test "genpatches-then-genbranch" {
  msg="add new.txt"
  echo "pile 1" > j.txt && git add j.txt && git commit -m "add new.txt"
  rev0=$(git rev-parse HEAD)

  git pile genpatches -m "$msg"
  git pile genbranch -i

  rev1=$(git rev-parse HEAD)
  [ "$(git diff $rev0..$rev1)" = "" ]
}

@test "genpatches-untracked-dir-then-genbranch" {
  echo "pile 1" > j.txt && git add j.txt && git commit -m "add new.txt"
  rev0=$(git rev-parse HEAD)

  git pile genpatches -o untracked-output-dir
  git pile genbranch -e untracked-output-dir -i

  rev1=$(git rev-parse HEAD)
  [ "$(git diff $rev0..$rev1)" = "" ]
}

# Check that genbranch to another branch name (with -b) works
# as expected
@test "genbranch-branch-name" {
  msg="add new.txt"
  echo "pile 1" > j.txt && git add j.txt && git commit -m "add new.txt"

  git pile genpatches -m "$msg"
  git pile genbranch -i -b test

  [ "$(git diff internal..test)" = "" ]
}

# Use genbranch-user-name and genbranch-user-email
# to trick git to always generate the same git objects/commits
# if nothing changed
@test "two-genbranch-same-sha" {
  msg="add new.txt"
  echo "pile 1" > j.txt && git add j.txt && git commit -m "add new.txt"
  rev0=$(git rev-parse HEAD)

  git config pile.genbranch-user-name = "pile bot"
  git config pile.genbranch-user-email = "git@pi.le"

  git pile genpatches -m "$msg"
  git pile genbranch -i
  git pile genbranch -i -b test

  rev0=$(git rev-parse internal)
  rev1=$(git rev-parse test)
  [ "$rev0" = "$rev1" ]
}

@test "genbranch-call-from-pile-worktree" {
  add_pile_commits 3 1
  git pile genbranch -i
  head=$(git rev-parse HEAD)

  # git-pile doesn't allow this because it would be very confusing
  # since -i is documented to be "inplace", in the currect worktree
  run ! git -C patches/ pile genbranch -i

  # without -i it should work as long as it's not checkout anywhere:
  # it's not ambiguous what the user  is trying to do
  git -C patches/ pile genbranch -b tmp
  [ "$head" = "$(git rev-parse tmp)" ]

  pushd patches
  # doesn't work as the internal branch has a checkout already
  run ! git pile genbranch
  popd
}

@test "genbranch-rev" {
  add_pile_commits 3 1
  git pile genbranch -i
  head=$(git rev-parse HEAD)

  add_pile_commits 1 4
  git pile genbranch -i

  git pile genbranch -i --pile-rev pile~1
  [ "$head" = "$(git rev-parse HEAD)" ]
}
