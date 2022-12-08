#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.7.0
  load common.bash

  create_simple_repo $BATS_FILE_TMPDIR/testrepo
}

setup() {
  load common.bash
  git clone "$BATS_FILE_TMPDIR/testrepo" "$BATS_TEST_TMPDIR/testrepo"
  pushd "$BATS_TEST_TMPDIR/testrepo"
}

@test "baseline" {
  head="$(git rev-parse HEAD)"

  git pile init -p pile -r internal
  git checkout -b internal

  [ "$head" = "$(git rev-parse internal)" ]
  [ "$head" = "$(git pile baseline)" ]
  [ "$head" = "$(git -C patches pile baseline)" ]
}

@test "baseline-multiple-pile" {
  git pile init -p pile -r internal

  git config extensions.worktreeConfig true
  git worktree add ../testrepo-old HEAD
  pushd ../testrepo-old

  git pile init -p pile-old -r internal-old -b HEAD^

  baseline_testrepo=$(git -C "$BATS_TEST_TMPDIR/testrepo" pile baseline)
  baseline_testrepo_patches=$(git -C "$BATS_TEST_TMPDIR/testrepo/patches" pile baseline)
  baseline_testrepo_old=$(git -C "$BATS_TEST_TMPDIR/testrepo-old" pile baseline)
  baseline_testrepo_old_patches=$(git -C "$BATS_TEST_TMPDIR/testrepo-old/patches" pile baseline)

  [ "$baseline_testrepo" = "$baseline_testrepo_patches" ]
  [ "$baseline_testrepo_old" = "$baseline_testrepo_old_patches" ]
  [ "$baseline_testrepo" != "$baseline_testrepo_old" ]
}
