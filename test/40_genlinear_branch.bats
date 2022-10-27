#!/usr/bin/env bats
setup_file() {
  bats_require_minimum_version 1.7.0
  load 'common'

  create_simple_repo "$BATS_FILE_TMPDIR/testrepo"
}

add_pile_commits() {
  local n_commits=$1
  local fn_number=$2

  for i in $(seq 1 $n_commits); do
    fn="foo${fn_number}.txt"
    touch $fn
    git add $fn
    git commit -m "Add $fn"
    git pile genpatches -m "Add patch adding $fn"
    let fn_number+=1
  done
}

setup() {
  git clone --bare "$BATS_FILE_TMPDIR/testrepo" "$BATS_TEST_TMPDIR/remoterepo"

  git clone "$BATS_TEST_TMPDIR/remoterepo" "$BATS_TEST_TMPDIR/testrepo"
  pushd "$BATS_TEST_TMPDIR/testrepo"
  git pile init
  git config pile.genbranch-user-name = "pile bot"
  git config pile.genbranch-user-email = "git@pi.le"
  git checkout -b internal

  add_pile_commits 3 1
  git push origin -u --all
}

# Check a bootstrap of genlinear branch works
@test "genlinear-branch-bootstrap" {
  git pile genlinear-branch -b internal-linear
  [ "$(git diff internal..internal-linear)" = "" ]
  [ "$(git log --format=%s pile)" = "$(git log --format=%s internal-linear)" ]

  trailers="$(git log --format="%N" --notes=refs/notes/internal-linear internal-linear | sed -e 's/pile-commit: //' -e '/^$/d')"
  [ "$(git log --format=%H pile)" = "$trailers" ]

  # since we built a very simple result-branch with just additions on top,
  # it's possible to check commit by commit
  i=0
  n=$(git rev-list --count internal-linear)
  let n-=2
  for i in $(seq 0 $n); do
    [ "$(git diff internal~$i internal-linear~$i)" = "" ]
  done
}

@test "genlinear-branch-incremental" {
  pile_rev0=$(git rev-parse pile)
  git pile genlinear-branch -b internal-linear
  rev0=$(git rev-parse internal-linear)

  # add more 4 commits
  add_pile_commits 3 4

  # make sure genlinear-branch picks up where it left of
  git pile genlinear-branch -b internal-linear
  [ $(git rev-list --count $rev0..internal-linear) = 3 ]

  trailers="$(git log --format="%N" --notes=refs/notes/internal-linear $rev0..internal-linear | sed -e 's/pile-commit: //' -e '/^$/d')"
  [ "$(git log --format=%H $pile_rev0..pile)" = "$trailers" ]
}
