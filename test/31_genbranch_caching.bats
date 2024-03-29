#!/usr/bin/env bats
setup_file() {
  bats_require_minimum_version 1.7.0
  load common.bash

  create_simple_repo "$BATS_FILE_TMPDIR/testrepo"
}

setup() {
  git clone --bare "$BATS_FILE_TMPDIR/testrepo" "$BATS_TEST_TMPDIR/remoterepo"

  git clone "$BATS_TEST_TMPDIR/remoterepo" "$BATS_TEST_TMPDIR/testrepo"
  pushd "$BATS_TEST_TMPDIR/testrepo"
  git pile init
  git config pile.genbranch-user-name "pile bot"
  git config pile.genbranch-user-email "git@pi.le"
  git checkout -b internal
  git push origin -u --all
}

# Usage: run_genbranch [--no-uncached-check] [<genbranch_cmd>...]
#
# Run genbranch and do common assertions.
#
# If <genbranch_cmd>... is not provided, `git pile genbranch -i` is used by
# default.
#
# This function checks if the command will generate exactly the same history
# generated by `git pile genbranch --no-cache -i`. This check can be disabled
# with --no-uncached-check.
run_genbranch() {
  local uncached_check="yes"
  if [[ "$1" = "--no-uncached-check" ]]; then
    uncached_check="no"
    shift
  fi

  if [[ $# -eq 0 ]]; then
    set -- git pile genbranch -i
  fi

  if [[ $uncached_check = "yes" ]]; then
    local saved_head=$(git rev-parse HEAD)
    git pile genbranch --no-cache -i
    local expected_hash=$(git rev-parse HEAD)
    git reset --hard $saved_head
  fi

  run --separate-stderr "$@"

  if [[ $uncached_check = "yes" ]]; then
    [ "$(git rev-parse HEAD)" = "$expected_hash" ]
  fi
}

# Usage: assert_cached <offset>
# The argument <offset> defines the expected number of patches skipped by
# genbranch. The special value -1 can be used to expect all patches to be
# skipped.
assert_cached() {
  local offset=${1:?Missing offset}
  local IFS_BKP="$IFS"
  local IFS=$'\n'
  local apply_lines=($(git log --reverse --format="Applying: %s" $(git pile baseline)..))
  IFS="$IFS_BKP"
  local commit_count=${#apply_lines[@]}
  local num_lines=${#lines[@]}

  if [[ $offset -eq -1 ]]; then
    offset=$commit_count
  fi

  (( commit_count - offset == num_lines ))

  local i
  for ((i = 0; i < num_lines; i++)); do
    [ "${lines[i]}" = "${apply_lines[offset + i]}" ]
  done
}

assert_not_cached() {
  assert_cached 0
}

assert_fully_cached() {
  assert_cached -1
}

# General caching checks
@test "genbranch-caching-general" {
  echo "pile 1" > j.txt && git add j.txt && git commit -m "1st commit after baseline"
  echo "pile 2" > j.txt && git add j.txt && git commit -m "2nd commit after baseline"
  echo "pile 3" > j.txt && git add j.txt && git commit -m "3rd commit after baseline"
  echo "pile 4" > j.txt && git add j.txt && git commit -m "4th commit after baseline"

  git pile genpatches -m "First pile commit"
  run_genbranch
  assert_not_cached
  tip_first_series=$(git rev-parse HEAD)

  git reset --hard HEAD~2
  echo "pile iii" > j.txt && git add j.txt && git commit -m "iii commit after baseline"
  echo "pile iv" > j.txt && git add j.txt && git commit -m "iv commit after baseline"
  git pile genpatches -m "Second pile commit"
  run_genbranch
  assert_cached 2

  git -C "$(git config pile.dir)" reset --hard HEAD~1
  run_genbranch
  assert_fully_cached
  [ $(git rev-parse HEAD) = "$tip_first_series" ]

  # Cases below should trigger a "full genbranch"

  # Using --no-uncached-check because we are changing committer information.
  run_genbranch --no-uncached-check git -c pile.genbranch-user-name="pile bot 2" pile genbranch -i
  assert_not_cached

  run_genbranch git pile genbranch -i --fix-whitespace
  assert_not_cached
  [[ "$stderr" = *"warning: Caching disabled because of non-default genbranch operation: using option --fix-whitespace"* ]]

  run_genbranch git -c pile.genbranch-use-cache=false pile genbranch -i
  assert_not_cached

  run_genbranch git pile genbranch -i --no-cache
  assert_not_cached

  run_genbranch git -c pile.genbranch-cache-path=other-file.pickle pile genbranch -i
  assert_not_cached
}

# Check that caching works as expected when updating with changes from other
# developers
@test "genbranch-caching-remote" {
  echo "pile 1" > j.txt && git add j.txt && git commit -m "1st commit after baseline"
  echo "pile 2" > j.txt && git add j.txt && git commit -m "2nd commit after baseline"
  echo "pile 3" > j.txt && git add j.txt && git commit -m "3rd commit after baseline"
  echo "pile 4" > j.txt && git add j.txt && git commit -m "4th commit after baseline"

  git pile genpatches -m "First pile commit"
  run_genbranch
  assert_not_cached
  git push origin --all -f

  # Do work on another repository: replace commit "2nd commit after baseline"
  git clone "$BATS_TEST_TMPDIR/remoterepo" "$BATS_TEST_TMPDIR/testrepo2"
  pushd "$BATS_TEST_TMPDIR/testrepo2"
  git config pile.genbranch-user-name "pile bot"
  git config pile.genbranch-user-email "git@pi.le"
  git checkout internal
  git pile setup origin/pile origin/internal
  git pile reset
  git reset --hard internal~3
  echo "pile ii" > j.txt && git add j.txt && git commit -m "ii commit after baseline"
  git cherry-pick -X theirs origin/internal~2..origin/internal
  git pile genpatches -m "Second pile commit"
  run_genbranch
  assert_not_cached
  git push origin --all -f
  popd

  # Update first repository with new changes, then replace commit "3rd commit
  # after baseline"
  git remote update
  git pile reset
  git reset --hard internal~2
  echo "pile iii" > j.txt && git add j.txt && git commit -m "iii commit after baseline"
  git cherry-pick -X theirs origin/internal~1..origin/internal
  git pile genpatches -m "Third pile commit"
  run_genbranch
  # Only commit "1st commit after baseline" should be used from the cache at
  # this point.
  assert_cached 1
}

# Check that caching works as expected when reordering commits
@test "genbranch-caching-reorder-commits" {
  echo "pile 1" > j.txt && git add j.txt && git commit -m "1st commit after baseline"
  echo "pile 2" > j.txt && git add j.txt && git commit -m "2nd commit after baseline"
  echo "pile 3" > j.txt && git add j.txt && git commit -m "3rd commit after baseline"
  echo "pile 4" > j.txt && git add j.txt && git commit -m "4th commit after baseline"

  git pile genpatches -m "First pile commit"
  run_genbranch
  assert_not_cached

  # Cache should still be used after reordering commits without modifying the
  # pile branch.
  rev=$(git rev-parse HEAD)
  commits=($(git rev-list --reverse HEAD~4..))
  git reset --hard HEAD~4
  git cherry-pick -X theirs "${commits[0]}" "${commits[3]}" "${commits[2]}" "${commits[1]}"
  run_genbranch
  assert_fully_cached
  [ $(git rev-parse HEAD) = "$rev" ]
}

# Check that only part of the cache is used after garbage collection
@test "genbranch-caching-gc" {
  echo "pile 1" > j.txt && git add j.txt && git commit -m "1st commit after baseline"
  echo "pile 2" > j.txt && git add j.txt && git commit -m "2nd commit after baseline"
  echo "pile 3" > j.txt && git add j.txt && git commit -m "3rd commit after baseline"
  echo "pile 4" > j.txt && git add j.txt && git commit -m "4th commit after baseline"

  git pile genpatches -m "First pile commit"
  run_genbranch
  assert_not_cached
  rev=$(git rev-parse HEAD)

  git reset --hard HEAD~3
  echo "pile ii" > j.txt && git add j.txt && git commit -m "ii commit after baseline"
  echo "pile iii" > j.txt && git add j.txt && git commit -m "iii commit after baseline"
  echo "pile iv" > j.txt && git add j.txt && git commit -m "iv commit after baseline"
  git pile genpatches -m "Second pile commit"
  run_genbranch
  assert_cached 1

  # After garbage collection, we expect that the last 3 commits from the first
  # version of the result branch to be removed, so that only the first patch can
  # be skipped.
  git -c gc.reflogExpire=now gc --prune=now
  ! git cat-file -e $rev
  git -C "$(git config pile.dir)" reset --hard HEAD~1
  # We need to use --no-uncached-check, otherwise the removed commits will be
  # recreated by the uncached run.
  run_genbranch --no-uncached-check
  assert_cached 1
}


# The genbranch command without --inplace uses a temporary worktree for the
# operation. Check that we update the cache with the correct commits (i.e. from
# the temporary worktree instead of the current one).
@test "genbranch-not-inplace" {
  echo "pile 1" > j.txt && git add j.txt && git commit -m "1st commit after baseline"
  echo "pile 2" > j.txt && git add j.txt && git commit -m "2nd commit after baseline"
  echo "pile 3" > j.txt && git add j.txt && git commit -m "3rd commit after baseline"
  echo "pile 4" > j.txt && git add j.txt && git commit -m "4th commit after baseline"

  git pile genpatches -m "First pile commit"
  run_genbranch git pile genbranch -f

  # Second run that uses the cache
  run_genbranch git pile genbranch -f
  assert_fully_cached
}


# Check that git pile correctly finds the cache file when genbranch is called
# from the patches directory.
@test "genbranch-caching-from-patches-dir" {
  echo "pile 1" > j.txt && git add j.txt && git commit -m "1st commit after baseline"
  echo "pile 2" > j.txt && git add j.txt && git commit -m "2nd commit after baseline"
  echo "pile 3" > j.txt && git add j.txt && git commit -m "3rd commit after baseline"
  echo "pile 4" > j.txt && git add j.txt && git commit -m "4th commit after baseline"

  git pile genpatches -m "First pile commit"
  run_genbranch

  run_genbranch git -C "$(git config pile.dir)" pile genbranch -f
  assert_fully_cached
}
