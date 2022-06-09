#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.7.0
  load 'common'

  create_simple_repo $BATS_FILE_TMPDIR/testrepo
}

setup() {
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
