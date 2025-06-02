#!/bin/bash

git_setup() {
    local TEST_GIT_VERSION=$1
    local git_version git_version_regex

    export PATH=/usr/local/git-${TEST_GIT_VERSION}.x/bin:$PATH
    git_version=$(git --version)
    git_version_regex="git version ${TEST_GIT_VERSION:1}\..*"
    if [[ ! $git_version =~ $git_version_regex ]]; then
        echo "::error Unexpcted $git_version"
        exit 1
    fi

    echo $git_version
}

run() {
    local TEST_GIT_VERSION=$1

    git_setup $TEST_GIT_VERSION

    echo -e "TAP version 13\r" > git-${TEST_GIT_VERSION}.tap
    bats --tap -T test | tee -a git-${TEST_GIT_VERSION}.tap
}
