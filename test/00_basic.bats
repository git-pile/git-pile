#!/usr/bin/env bats

setup() {
  bats_require_minimum_version 1.7.0
  load common.bash
}

@test "version" {
  run --separate-stderr -0 git pile --version
  [[ "$output" =~ git-pile[[:space:]][0-9]+\.[0-9]+.* ]]
}

@test "missing-arguments" {
  run --separate-stderr ! git pile
  [[ "${lines[0]}" = "usage: git-pile"* ]]
}

@test "invalid-option" {
  run --separate-stderr ! git pile --foo
  #[[ "${stderr_lines[0]}" = "usage: git-pile"* ]]
}

@test "invalid-command" {
  run --separate-stderr ! git pile whatever-non-existent-subcommand
  #[[ "${stderr_lines[0]}" = "usage: git-pile"* ]]
}

@test "help" {
  run --separate-stderr -0 git pile -h
  [[ "${lines[0]}" = "usage: git-pile"* ]]

  # use git-pile, as otherwise git itself will try
  # to open the man page for git-pile, which is not
  # what we want
  run --separate-stderr -0 git-pile --help
  [[ "${lines[0]}" = "usage: git-pile"* ]]
}
