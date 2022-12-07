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

# continuation to setup() above, for tests that need it
setup_second_pile() {
  local suffix=$1
  add_pile_commits 1 10
  git push origin pile:pile${suffix} internal:internal${suffix}
}

@test "setup" {
  git clone "$BATS_TEST_TMPDIR/remoterepo" "$BATS_TEST_TMPDIR/testrepo2"
  pushd "$BATS_TEST_TMPDIR/testrepo2"
  git pile setup origin/pile origin/internal
  [ "$(git -C ../testrepo rev-parse internal)" = "$(git rev-parse internal)" ]
  [ "$(git -C ../testrepo rev-parse pile)" = "$(git rev-parse pile)" ]
}

@test "setup-multiple-pile" {
  setup_second_pile -next

  git clone "$BATS_TEST_TMPDIR/remoterepo" "$BATS_TEST_TMPDIR/testrepo2"
  pushd "$BATS_TEST_TMPDIR/testrepo2"

  # requirement for working with multiple piles
  git config extensions.worktreeConfig true
  git pile setup origin/pile origin/internal

  git worktree add ../testrepo2-next HEAD
  pushd ../testrepo2-next
  git pile setup origin/pile-next origin/internal-next
  git checkout internal-next

  [ "$(git rev-parse pile)" = "$(git rev-parse origin/pile)" ]
  [ "$(git rev-parse internal)" = "$(git rev-parse origin/internal)" ]
  [ "$(git rev-parse pile-next)" = "$(git rev-parse origin/pile-next)" ]
  [ "$(git rev-parse internal-next)" = "$(git rev-parse origin/internal-next)" ]
}

# same thing as setup-multiple-pile, but use a trailing slash when setting up the pile
# and make sure git-pile can work with it. some git versions (e.g. 2.25) have
# issues without a slash, so git-pile automatically adds one. Let's make sure
# if we have a double slash on commands to git-worktree add it still works
@test "setup-multiple-pile-trailing-slash" {
  setup_second_pile -next

  git clone "$BATS_TEST_TMPDIR/remoterepo" "$BATS_TEST_TMPDIR/testrepo2"
  pushd "$BATS_TEST_TMPDIR/testrepo2"

  # requirement for working with multiple piles
  git config extensions.worktreeConfig true
  git pile setup origin/pile origin/internal

  git worktree add ../testrepo2-next HEAD
  pushd ../testrepo2-next
  git pile setup -d patches/ origin/pile-next origin/internal-next
  git checkout internal-next

  [ "$(git rev-parse pile)" = "$(git rev-parse origin/pile)" ]
  [ "$(git rev-parse internal)" = "$(git rev-parse origin/internal)" ]
  [ "$(git rev-parse pile-next)" = "$(git rev-parse origin/pile-next)" ]
  [ "$(git rev-parse internal-next)" = "$(git rev-parse origin/internal-next)" ]
}
