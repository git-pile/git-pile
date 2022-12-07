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
  git config user.name "pile dev"
  git config user.email "dev@pi.le"
  git checkout -b internal
  git push origin -u --all
}

add_commits_and_format_patch() {
  # Add stuff that will be the "base" for format-patch.
  for ((i = 0; i < 10; i++)); do
    echo "pile $i"
  done > j.txt && git add j.txt && git commit -m "1st commit"
  for ((i = 10; i < 20; i++)); do
    echo "pile $i"
  done >> j.txt && git add j.txt && git commit -m "2nd commit"
  git pile genpatches -c -m "First pile commit"
  git push origin --all

  # Modify the branch and format-patch.
  sed -i 's/^pile 15$/pile xv/' j.txt && git add j.txt \
    && git commit --amend -m "2nd commit modified"
  echo "pile 21" >> j.txt && git add j.txt && git commit -m "3rd commit"
  echo "pile 22" >> j.txt && git add j.txt && git commit -m "4th commit"
  dev_tip=$(git rev-parse HEAD)
  git pile format-patch -o "$BATS_TEST_TMPDIR/format-patch-out"
  git pile reset

  # Assert that we have the expected output files.
  actual=$(cd "$BATS_TEST_TMPDIR/format-patch-out" && echo *)
  expected="0000-cover-letter.patch 0001-3rd-commit.patch 0002-4th-commit.patch 0003-full-tree-diff.patch"
  [ "$actual" = "$expected" ]

  sed -i \
    -e 's/\*\*\* SUBJECT HERE \*\*\*/Second pile commit/' \
    -e 's/\*\*\* BLURB HERE \*\*\*/Will be applied with am!/' \
    "$BATS_TEST_TMPDIR/format-patch-out/0000-cover-letter.patch"
}

@test "format-patch-and-am" {
  add_commits_and_format_patch
  git pile am "$BATS_TEST_TMPDIR/format-patch-out/0000-cover-letter.patch"

  actual=$(git show -s --format=%s%n%b $(git config pile.pile-branch))
  expected=$'Second pile commit\nWill be applied with am!'
  [ "$actual" = "$expected" ]

  git pile genbranch -i
  range_diff=$(git range-diff -s $dev_tip... | sed "/^[0-9]\+:\s\+[0-9a-f]\+ =/d")
  [ "$range_diff" = "" ]
}

@test "am-genbranch" {
  add_commits_and_format_patch
  git pile am -g "$BATS_TEST_TMPDIR/format-patch-out/0000-cover-letter.patch"

  actual=$(git show -s --format=%s%n%b $(git config pile.pile-branch))
  expected=$'Second pile commit\nWill be applied with am!'
  [ "$actual" = "$expected" ]

  range_diff=$(git range-diff -s $dev_tip... | sed "/^[0-9]\+:\s\+[0-9a-f]\+ =/d")
  [ "$range_diff" = "" ]
}

@test "empty-old-range" {
  echo "pile 1" > j.txt && git add j.txt && git commit -m "1st commit"
  echo "pile 2" > j.txt && git add j.txt && git commit -m "2nd commit"
  git pile format-patch -o "$BATS_TEST_TMPDIR/format-patch-out"
  git pile am "$BATS_TEST_TMPDIR/format-patch-out/0000-cover-letter.patch"

  actual=$(cd "$BATS_TEST_TMPDIR/format-patch-out" && echo *)
  expected="0000-cover-letter.patch 0001-1st-commit.patch 0002-2nd-commit.patch 0003-full-tree-diff.patch"
  [ "$actual" = "$expected" ]

  actual=$(cat "$(git config pile.dir)/series" | sed '/^#\|^$/d')
  expected=$'0001-1st-commit.patch\n0001-2nd-commit.patch'
  [ "$actual" = "$expected" ]
}

@test "empty-new-range" {
  echo "pile 1" > j.txt && git add j.txt && git commit -m "1st commit"
  echo "pile 2" > j.txt && git add j.txt && git commit -m "2nd commit"
  git pile genpatches -c -m "First pile commit"
  git push origin --all

  git reset --hard $(git pile baseline)
  git pile format-patch -o "$BATS_TEST_TMPDIR/format-patch-out"
  git pile am "$BATS_TEST_TMPDIR/format-patch-out/0000-cover-letter.patch"

  actual=$(cd "$BATS_TEST_TMPDIR/format-patch-out" && echo *)
  expected="0000-cover-letter.patch 0001-full-tree-diff.patch"
  [ "$actual" = "$expected" ]

  actual=$(cat "$(git config pile.dir)/series" | sed '/^#\|^$/d')
  expected=""
  [ "$actual" = "$expected" ]
}
