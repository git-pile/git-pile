#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.7.0
  load 'common'

  create_simple_repo $BATS_FILE_TMPDIR/testrepo
}

setup() {
  git clone $BATS_FILE_TMPDIR/testrepo $BATS_TEST_TMPDIR/testrepo
}

@test "init" {
  pushd "$BATS_TEST_TMPDIR/testrepo"

  git pile init -p pile -r internal
  [ -d patches ]
  [ "$(git rev-parse HEAD)" = "$(git pile baseline)" ]

  # double init fails
  run ! git pile init -p pile -r internal
  git pile destroy

  # init again passes
  git pile init -p pile -r internal
}
