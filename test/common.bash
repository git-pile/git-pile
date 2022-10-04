#!/bin/bash

dump_stderr_console() {
  printf '## %s\n' "${stderr_lines[@]}" >&3
}

dump_stderr() {
  printf '## %s\n' "${stderr_lines[@]}" >&2
}

dump_stdout_console() {
  printf '## %s\n' "${lines[@]}" >&3
}

dump_stdout() {
  printf '## %s\n' "${lines[@]}"
}

create_simple_repo() {
  repo="$1"

  git -c init.defaultBranch=master init "$repo"
  pushd "$repo"
  touch a b c
  git add a; git commit -m "Add a"
  git add b; git commit -m "Add b"
  git add c; git commit -m "Add c"
  popd
}

if [[ -n $COVERAGE ]]; then
    export PATH="$BATS_TEST_DIRNAME/coverage-shim:$PATH"
fi
