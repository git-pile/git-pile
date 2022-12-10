# SPDX-License-Identifier: LGPL-2.1+
"""
Common git utilities.
"""

import contextlib
import os
import os.path as op
import subprocess
import sys
import tempfile

from .helpers import (
    git,
    git_can_fail,
    nul_f,
)


def git_branch_exists(branch):
    return git(f"show-ref --verify --quiet refs/heads/{branch}", check=False).returncode == 0


# Mimic git bevavior to find the editor. We need to do this since
# GIT_EDITOR was overriden
def git_get_editor():
    return (
        os.environ.get("GIT_EDITOR", None)
        or git(["config", "core.editor"], check=False).stdout.strip()
        or os.environ.get("VISUAL", None)
        or os.environ.get("EDITOR", None)
        or "vi"
    )


def git_init(branch, directory):
    if git_can_fail(f"-C {directory} init -b {branch}", stderr=nul_f).returncode == 0:
        return

    # git-init in git < 2.28 doesn't have a -b switch. Try to do that ourselves
    git(f"-C {directory} init")
    git(f"-C {directory} checkout -b {branch}")


def git_ref_exists(ref):
    return git(f"show-ref --verify --quiet {ref}", check=False).returncode == 0


def git_ref_is_ancestor(ancestor, ref):
    return git_can_fail(f"merge-base --is-ancestor {ancestor} {ref}").returncode == 0


def git_remote_branch_exists(remote_and_branch):
    return git(f"show-ref --verify --quiet refs/remotes/{remote_and_branch}", check=False).returncode == 0


# Return the git root of current worktree or abort when not in a worktree
def git_root_or_die():
    try:
        return git("rev-parse --show-toplevel").stdout.strip("\n")
    except subprocess.CalledProcessError:
        sys.exit(1)


@contextlib.contextmanager
def git_split_index(path="."):
    if git_worktree_config_extension_enabled():
        config_cmd = "config --worktree"
    else:
        config_cmd = "config"

    # only change if not explicitely configure in config
    change_split_index = git_can_fail(f"-C {path} {config_cmd} --get core.splitIndex").returncode != 0

    if not change_split_index:
        try:
            yield
        finally:
            return

    change_shared_index_expire = git_can_fail(f"-C {path} {config_cmd} --get splitIndex.sharedIndexExpire").returncode != 0

    try:
        git(f"-C {path} update-index --split-index")
        if change_shared_index_expire:
            git(f"-C {path} {config_cmd} splitIndex.sharedIndexExpire now")

        yield
    finally:
        git(f"-C {path} update-index --no-split-index")
        if change_shared_index_expire:
            git(f"-C {path} {config_cmd} --unset splitIndex.sharedIndexExpire")


# Create a temporary directory to checkout a detached branch with git-worktree
# making sure it gets deleted (both the directory and from git-worktree) when
# we finished using it.
#
# To be used in `with` context handling.
@contextlib.contextmanager
def git_temporary_worktree(commit, dir, prefix="git-pile-worktree"):
    class Break(Exception):
        """Break out of the with statement"""

    try:
        with tempfile.TemporaryDirectory(dir=dir, prefix=prefix) as d:
            git(f"worktree add --detach --checkout {d} {commit}", stdout=nul_f, stderr=nul_f)
            yield d
    finally:
        git(f"worktree remove {d}")


def git_worktree_config_extension_enabled():
    return git_can_fail("config --get --bool extensions.worktreeConfig", stderr=nul_f).stdout.strip() == "true"


# Return the path a certain branch is checked out at
# or None.
def git_worktree_get_checkout_path(root, branch):
    state = dict()
    out = git(f"-C {root} worktree list --porcelain").stdout.split("\n")
    path = None

    for l in out:
        if not l:
            # end block
            if state.get("branch", None) == "refs/heads/" + branch:
                path = op.realpath(state["worktree"])
                break

            state = dict()
            continue

        v = l.split(" ")
        state[v[0]] = v[1] if len(v) > 1 else None

    # make sure `git worktree list` is in sync with reality
    if not path or not op.isdir(path):
        return None

    return path


# Get the git dir (aka .git) directory for the worktree related to
# the @path. @path defaults to CWD
def git_worktree_get_git_dir(path=".", force_absolute=False):
    gitdir = git(f"-C {path} rev-parse --git-dir").stdout.strip("\n")
    if force_absolute:
        # Manpage for git-rev-parse says the following about the --git-dir
        # option: "The path shown, when relative, is relative to the current
        # working directory". Since it does not say when the path will be
        # relative or not, let's do the necessary transformation when the caller
        # wants an absolute path and use ``op.realpath()`` to remain consistent
        # with the codebase.
        if not op.isabs(gitdir):
            gitdir = op.abspath(op.join(path, gitdir))
        gitdir = op.realpath(gitdir)
    return gitdir


def git_worktree_list(root):
    out = git(f"-C {root} worktree list --porcelain").stdout.splitlines()
    ret = tuple(op.realpath(s.split(maxsplit=1)[1]) for s in out if s.startswith("worktree"))
    return ret
