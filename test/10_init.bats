#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.7.0
  load common.bash

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

@test "init-multiple-pile" {
  pushd "$BATS_TEST_TMPDIR/testrepo"

  # requirement for working with multiple piles
  git config extensions.worktreeConfig true

  # create the first setup (pile, internal)
  git pile init -p pile -r internal
  git checkout -b internal
  git push -u origin pile internal

  # add another worktree to work on
  git worktree add --checkout -b internal-next ../testrepo-next
  cd ../testrepo-next

  # create the second setup (pile-next, internal-next)
  # and add something on top to compare later that it doesn't
  # match in the first setup
  git pile init -p pile-next -r internal-next
  touch pile-next-file.txt
  git add pile-next-file.txt
  git commit -m "Add pile-next-file.txt"
  git pile genpatches -m "Add patch adding pile-next-file.txt"
  # make sure git-pile managed the separate config in second setup
  [ "$(git config pile.pile-branch)" = "pile-next" ]

  cd ../testrepo
  # make sure git-pile managed the separate config in first setup
  [ "$(git config pile.pile-branch)" = "pile" ]
  git pile reset
  [ "$(git rev-parse internal)" != "$(git rev-parse internal-next)" ]
  [ "$(git rev-parse pile)" != "$(git rev-parse pile-next)" ]
  [ ! -f pile-next-file.txt ]
}
