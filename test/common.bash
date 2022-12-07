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

# continuation to a setup() phase, for tests that need it assumptions: there
# are already a pile and an internal branches created
setup_second_pile() {
  local suffix=$1
  add_pile_commits 1 10
  git push origin pile:pile${suffix} internal:internal${suffix}
}

if [[ -n $COVERAGE ]] && ! [[ "$PATH" =~ (^|:)"$BATS_TEST_DIRNAME/coverage-shim"(:|$) ]]; then
    export PATH="$BATS_TEST_DIRNAME/coverage-shim:$PATH"
fi
