#!/usr/bin/env bats
setup_file() {
  bats_require_minimum_version 1.7.0
  load 'common'

  create_simple_repo "$BATS_FILE_TMPDIR/testrepo"
}

setup() {
  git clone --bare "$BATS_FILE_TMPDIR/testrepo" "$BATS_TEST_TMPDIR/remoterepo"

  git clone "$BATS_TEST_TMPDIR/remoterepo" "$BATS_TEST_TMPDIR/testrepo"
  pushd "$BATS_TEST_TMPDIR/testrepo"
  git pile init
  git config pile.genbranch-user-name = "pile bot"
  git config pile.genbranch-user-email = "git@pi.le"
  git checkout -b internal
  git push origin -u --all
}

# General caching checks
@test "genbranch-caching-general" {
  echo "pile 1" > j.txt && git add j.txt && git commit -m "1st commit after baseline"
  echo "pile 2" > j.txt && git add j.txt && git commit -m "2nd commit after baseline"
  echo "pile 3" > j.txt && git add j.txt && git commit -m "3rd commit after baseline"
  echo "pile 4" > j.txt && git add j.txt && git commit -m "4th commit after baseline"

  git pile genpatches -m "First pile commit"
  run --separate-stderr git pile genbranch -i
  [ "${lines[0]}" = "Applying: 1st commit after baseline" ]
  [ "${lines[1]}" = "Applying: 2nd commit after baseline" ]
  [ "${lines[2]}" = "Applying: 3rd commit after baseline" ]
  [ "${lines[3]}" = "Applying: 4th commit after baseline" ]
  [ ${#lines[@]} -eq 4 ]

  tip_first_series=$(git rev-parse HEAD)

  git reset --hard HEAD~2

  echo "pile iii" > j.txt && git add j.txt && git commit -m "iii commit after baseline"
  echo "pile iv" > j.txt && git add j.txt && git commit -m "iv commit after baseline"

  git pile genpatches -m "Second pile commit"
  run --separate-stderr git pile genbranch -i
  [ "${lines[0]}" = "Applying: iii commit after baseline" ]
  [ "${lines[1]}" = "Applying: iv commit after baseline" ]
  [ ${#lines[@]} -eq 2 ]

  git -C "$(git config pile.dir)" reset --hard HEAD~1
  run --separate-stderr git pile genbranch -i
  [ ${#lines} -eq 0 ]
  [ $(git rev-parse HEAD) = "$tip_first_series" ]

  # Cases below should trigger a "full genbranch"

  run --separate-stderr git -c pile.genbranch-user-name="pile bot 2" pile genbranch -i
  [ "${lines[0]}" = "Applying: 1st commit after baseline" ]
  [ "${lines[1]}" = "Applying: 2nd commit after baseline" ]
  [ "${lines[2]}" = "Applying: 3rd commit after baseline" ]
  [ "${lines[3]}" = "Applying: 4th commit after baseline" ]
  [ ${#lines[@]} -eq 4 ]

  run --separate-stderr git pile genbranch -i --fix-whitespace
  [ "${lines[0]}" = "Applying: 1st commit after baseline" ]
  [ "${lines[1]}" = "Applying: 2nd commit after baseline" ]
  [ "${lines[2]}" = "Applying: 3rd commit after baseline" ]
  [ "${lines[3]}" = "Applying: 4th commit after baseline" ]
  [ ${#lines[@]} -eq 4 ]
  [[ "$stderr" = *"warning: Caching disabled because of non-default genbranch operation: using option --fix-whitespace"* ]]

  run --separate-stderr git -c pile.genbranch-use-cache=false pile genbranch -i
  [ "${lines[0]}" = "Applying: 1st commit after baseline" ]
  [ "${lines[1]}" = "Applying: 2nd commit after baseline" ]
  [ "${lines[2]}" = "Applying: 3rd commit after baseline" ]
  [ "${lines[3]}" = "Applying: 4th commit after baseline" ]
  [ ${#lines[@]} -eq 4 ]

  run --separate-stderr git pile genbranch -i --no-cache
  [ "${lines[0]}" = "Applying: 1st commit after baseline" ]
  [ "${lines[1]}" = "Applying: 2nd commit after baseline" ]
  [ "${lines[2]}" = "Applying: 3rd commit after baseline" ]
  [ "${lines[3]}" = "Applying: 4th commit after baseline" ]
  [ ${#lines[@]} -eq 4 ]

  run --separate-stderr git -c pile.genbranch-cache-path=other-file.pickle pile genbranch -i
  [ "${lines[0]}" = "Applying: 1st commit after baseline" ]
  [ "${lines[1]}" = "Applying: 2nd commit after baseline" ]
  [ "${lines[2]}" = "Applying: 3rd commit after baseline" ]
  [ "${lines[3]}" = "Applying: 4th commit after baseline" ]
  [ ${#lines[@]} -eq 4 ]
}

# Check that caching works as expected when updating with changes from other
# developers
@test "genbranch-caching-remote" {
  echo "pile 1" > j.txt && git add j.txt && git commit -m "1st commit after baseline"
  echo "pile 2" > j.txt && git add j.txt && git commit -m "2nd commit after baseline"
  echo "pile 3" > j.txt && git add j.txt && git commit -m "3rd commit after baseline"
  echo "pile 4" > j.txt && git add j.txt && git commit -m "4th commit after baseline"

  git pile genpatches -m "First pile commit"
  git pile genbranch -i
  git push origin --all -f

  # Do work on another repository: replace commit "2nd commit after baseline"
  git clone "$BATS_TEST_TMPDIR/remoterepo" "$BATS_TEST_TMPDIR/testrepo2"
  pushd "$BATS_TEST_TMPDIR/testrepo2"
  git config pile.genbranch-user-name = "pile bot"
  git config pile.genbranch-user-email = "git@pi.le"
  git checkout internal
  git pile setup origin/pile origin/internal
  git pile reset
  git reset --hard internal~3
  echo "pile ii" > j.txt && git add j.txt && git commit -m "ii commit after baseline"
  git cherry-pick -X theirs origin/internal~2..origin/internal
  git pile genpatches -m "Second pile commit"
  git pile genbranch -i
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
  run --separate-stderr git pile genbranch -i
  # Only commit "1st commit after baseline" should be used from the cache at
  # this point.
  [ "${lines[0]}" = "Applying: ii commit after baseline" ]
  [ "${lines[1]}" = "Applying: iii commit after baseline" ]
  [ "${lines[2]}" = "Applying: 4th commit after baseline" ]
  [ ${#lines[@]} -eq 3 ]
}

# Check that caching works as expected when reordering commits
@test "genbranch-caching-reorder-commits" {
  echo "pile 1" > j.txt && git add j.txt && git commit -m "1st commit after baseline"
  echo "pile 2" > j.txt && git add j.txt && git commit -m "2nd commit after baseline"
  echo "pile 3" > j.txt && git add j.txt && git commit -m "3rd commit after baseline"
  echo "pile 4" > j.txt && git add j.txt && git commit -m "4th commit after baseline"

  git pile genpatches -m "First pile commit"
  run --separate-stderr git pile genbranch -i
  [ "${lines[0]}" = "Applying: 1st commit after baseline" ]
  [ "${lines[1]}" = "Applying: 2nd commit after baseline" ]
  [ "${lines[2]}" = "Applying: 3rd commit after baseline" ]
  [ "${lines[3]}" = "Applying: 4th commit after baseline" ]
  [ ${#lines[@]} -eq 4 ]

  # Cache should still be used after reordering commits without modifying the
  # pile branch.
  rev=$(git rev-parse HEAD)
  commits=($(git rev-list --reverse HEAD~4..))
  git reset --hard HEAD~4
  git cherry-pick -X theirs "${commits[0]}" "${commits[3]}" "${commits[2]}" "${commits[1]}"
  run --separate-stderr git pile genbranch -i
  [ ${#lines} -eq 0 ]
  [ $(git rev-parse HEAD) = "$rev" ]
}

# Check that only part of the cache is used after garbage collection
@test "genbranch-caching-gc" {
  echo "pile 1" > j.txt && git add j.txt && git commit -m "1st commit after baseline"
  echo "pile 2" > j.txt && git add j.txt && git commit -m "2nd commit after baseline"
  echo "pile 3" > j.txt && git add j.txt && git commit -m "3rd commit after baseline"
  echo "pile 4" > j.txt && git add j.txt && git commit -m "4th commit after baseline"

  git pile genpatches -m "First pile commit"
  run --separate-stderr git pile genbranch -i
  [ "${lines[0]}" = "Applying: 1st commit after baseline" ]
  [ "${lines[1]}" = "Applying: 2nd commit after baseline" ]
  [ "${lines[2]}" = "Applying: 3rd commit after baseline" ]
  [ "${lines[3]}" = "Applying: 4th commit after baseline" ]
  [ ${#lines[@]} -eq 4 ]
  rev=$(git rev-parse HEAD)

  git reset --hard HEAD~3
  echo "pile ii" > j.txt && git add j.txt && git commit -m "ii commit after baseline"
  echo "pile iii" > j.txt && git add j.txt && git commit -m "iii commit after baseline"
  echo "pile iv" > j.txt && git add j.txt && git commit -m "iv commit after baseline"
  git pile genpatches -m "Second pile commit"
  run --separate-stderr git pile genbranch -i
  [ "${lines[0]}" = "Applying: ii commit after baseline" ]
  [ "${lines[1]}" = "Applying: iii commit after baseline" ]
  [ "${lines[2]}" = "Applying: iv commit after baseline" ]
  [ ${#lines[@]} -eq 3 ]

  # After garbage collection, we expect that the last 3 commits from the first
  # version of the result branch to be removed, so that only the first patch can
  # be skipped.
  git -c gc.reflogExpire=now gc --prune=now
  ! git cat-file -e $rev
  git -C "$(git config pile.dir)" reset --hard HEAD~1
  run --separate-stderr git pile genbranch -i
  [ "${lines[0]}" = "Applying: 2nd commit after baseline" ]
  [ "${lines[1]}" = "Applying: 3rd commit after baseline" ]
  [ "${lines[2]}" = "Applying: 4th commit after baseline" ]
  [ ${#lines[@]} -eq 3 ]
}
