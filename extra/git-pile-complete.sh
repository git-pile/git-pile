#!/bin/bash

function _git_pile() {
    if [ "$(type -t _python_argcomplete_global)" == "function" ]; then
        COMP_REPLY=();
        _python_argcomplete_global git-pile;
    fi
}
complete -o default -o bashdefault -D -F _git_pile git-pile
