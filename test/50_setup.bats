#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.7.0
  load 'common'

  create_simple_repo $BATS_FILE_TMPDIR/testrepo
}

add_pile_commits() {
  local n_commits=$1
  local fn_number=$2

  for (( i=0; i < n_commits; i++, fn_number++ )); do
    fn="foo${fn_number}.txt"
    touch $fn
    git add $fn
    git commit -m "Add $fn"
    git pile genpatches -m "Add patch adding $fn"
  done
}

setup() {
  git clone --bare "$BATS_FILE_TMPDIR/testrepo" "$BATS_TEST_TMPDIR/remoterepo"

  git clone "$BATS_TEST_TMPDIR/remoterepo" "$BATS_TEST_TMPDIR/testrepo"
  pushd "$BATS_TEST_TMPDIR/testrepo"
  git pile init
  git checkout -b internal

  add_pile_commits 3 1
  git push origin -u --all
}

@test "setup" {
  git clone "$BATS_TEST_TMPDIR/remoterepo" "$BATS_TEST_TMPDIR/testrepo2"
  pushd "$BATS_TEST_TMPDIR/testrepo2"
  git pile setup origin/pile origin/internal
  [ "$(git -C ../testrepo rev-parse internal)" = "$(git rev-parse internal)" ]
  [ "$(git -C ../testrepo rev-parse pile)" = "$(git rev-parse pile)" ]
}

@test "setup-multiple-pile" {
  git pile setup origin/pile origin/internal
  pile_head=$(git rev-parse pile)
  internal_head=$(git rev-parse internal)

  add_pile_commits 1 10

  git push origin pile:pile-next internal:internal-next
  pile_next_head=$(git rev-parse pile)
  internal_next_head=$(git rev-parse internal)
  git pile reset

  git clone "$BATS_TEST_TMPDIR/remoterepo" "$BATS_TEST_TMPDIR/testrepo2"
  pushd "$BATS_TEST_TMPDIR/testrepo2"
  # requirement for working with multiple piles
  git config extensions.worktreeConfig true
  git pile setup origin/pile origin/internal
  [ "$(git rev-parse pile)" = "$pile_head" ]
  [ "$(git rev-parse internal)" = "$internal_head" ]

  git worktree add ../testrepo2-next HEAD
  pushd ../testrepo2-next
  git pile setup origin/pile-next origin/internal-next
  git checkout internal-next
  [ "$(git rev-parse pile-next)" = "$pile_next_head" ]
  [ "$(git rev-parse internal-next)" = "$internal_next_head" ]
}
