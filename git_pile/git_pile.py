#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1+

import argparse
import os
import os.path as op
import shutil
import sys
import tempfile

try:
    import argcomplete
except ImportError:
    pass

from .helpers import run_wrapper

# external commands
git = run_wrapper('git', capture=True)

nul_f = open(os.devnull, 'w')


def fatal(s):
    print("fatal: %s" % s, file=sys.stderr)
    sys.exit(1)

def error(s):
    print("error: %s" % s, file=sys.stderr)


class Config:
    def __init__(self):
        self.dir = ""
        self.result_branch = ""
        self.pile_branch = ""
        self.base_branch = ""

        s = git(["config", "--get-regex", "pile\\.*"]).stdout.strip()
        for kv in s.split('\n'):
            key, value = kv.strip().split()
            # pile.*
            key = key[5:].replace('-', '_')
            setattr(self, key, value)

    def is_valid(self):
        return self.dir != '' and self.result_branch != '' and self.pile_branch != ''

    def check_is_valid(self):
        if not self.is_valid():
            error("git-pile configuration is not valid. Configure it first with git-pile init")
            return False

        return True


def git_branch_exists(branch):
    return git("show-ref --verify --quiet refs/heads/%s" % branch, check=False).returncode == 0


def cmd_init(args):
    # TODO: check if already initialized
    # TODO: check if arguments make sense
    git("config pile.dir %s" % args.dir)
    git("config pile.pile-branch %s" % args.pile_branch)
    git("config pile.base-branch %s" % args.base_branch)
    git("config pile.result-branch %s" % args.result_branch)

    config = Config()

    # TODO: remove prints
    print("dir=%s\npile-branch=%s\nbase-branch=%s\nresult-branch=%s" %
          (config.dir, config.pile_branch, config.base_branch,
           config.result_branch))
    print("is-valid=%s" % config.is_valid())

    if not git_branch_exists(config.pile_branch):
        # Create and checkout an orphan branch named `config.pile_branch` at the
        # `config.dir` location. Unfortunately git-branch can't do that;
        # git-checkout has a --orphan option, but that would necessarily
        # checkout the branch and the user would be left wondering what
        # happened if any command here on fails.
        #
        # Workaround is to do that ourselves with a temporary repository
        with tempfile.TemporaryDirectory() as d:
            git("-C %s init" % d)
            with open(op.join(d, "config"), "w") as f:
                rev = git("rev-parse %s" % config.base_branch).stdout.strip()
                f.write("BASELINE=%s" % rev)
            git("-C %s add -A" % d)
            git(["-C", d, "commit", "-m", "Initial git-pile configuration"])

            # Temporary repository created, now let's fetch and create our branch
            git("fetch %s master:%s" % (d, config.pile_branch), stdout=nul_f, stderr=nul_f)
            git("worktree add --checkout %s %s" % (config.dir, config.pile_branch),
                stdout=nul_f, stderr=nul_f)

    return 0


def fix_duplicate_patch_name(dest, path, max_retries):
    fn = op.basename(path)
    l = len(fn)
    n = 1

    while op.exists(op.join(dest, fn)):
        n += 1
        # arbitrary number of retries
        if n > max_retries:
            raise Exception("wat!?! %s (max_retries=%d)" % (path, max_retries))
        fn = "%s-%d.patch" % (fn[:l - 6], n)

    return op.join(dest, fn)


def rm_patches(dest):
    with os.scandir(dest) as it:
        for entry in it:
            if not entry.is_file() or not entry.name.endswith(".patch"):
                continue

            try:
                os.remove(entry.path)
            except PermissionError:
                fatal("Could not remove %s: permission denied" % entry.path)


def has_patches(dest):
    try:
        with os.scandir(dest) as it:
            for entry in it:
                if entry.is_file() and entry.name.endswith(".patch"):
                    it.close()
                    return True
    except FileNotFoundError:
        pass

    return False


def cmd_genpatches(args):
    config = Config()
    if not config.check_is_valid():
        return 1

    # Do's and don'ts to generate patches to be used as an "always evolving
    # series":
    #
    # 1) Do not add `git --version` to the signature to avoid changing every patches when regenerating
    #    from different machines
    # 2) Do not number the patches on the subject to avoid polluting the diff when patches are reordered,
    #    or new patches enter in the middle
    # 3) Do not number the files: numbers will change when patches are added/removed
    # 4) To avoid filename clashes due to (3), check for each patch if a file
    #    already exists and workaround it
    if args.commit_range != "":
        commit_range = args.commit_range
    else:
        commit_range = "%s..%s" % (config.base_branch, config.result_branch)

    commit_list = git("rev-list --reverse %s" % commit_range).stdout.strip().split('\n')

    # Do everything in a temporary directory and once we know it went ok, move
    # to the final destination - we can use os.rename() since we are creating
    # the directory and using a subdir as staging
    with tempfile.TemporaryDirectory() as d:
        staging = op.join(d, "staging")
        series = []
        for c in commit_list:
            path_orig = git(["format-patch", "--zero-commit", "--signature=", "-o", staging, "-N", "-1", c]).stdout.strip()
            path = fix_duplicate_patch_name(d, path_orig, len(commit_list))
            os.rename(path_orig, path)
            series.append(path)

        os.rmdir(staging)

        # Be a little careful here: the user might have passed e.g. /tmp: we
        # don't want to remove patches there to avoid surprises
        if args.output_directory != "":
            output = args.output_directory
            if has_patches(output) and not args.force:
                fatal("'%s' is not default output directory and has patches in it.\n"
                      "Force with --force or pass an empty/non-existent directory" % output)
        else:
            output = config.dir

        os.makedirs(output, exist_ok=True)
        rm_patches(output)

        for p in series:
            s = shutil.copy(p, output)

        with open(op.join(output, "series"), "w") as f:
            f.write("# Auto-generated by git-pile's genpatches\n\n")
            for s in series:
                f.write(op.basename(s))
                f.write("\n")

    return 0


# Temporary command to help with development
def cmd_destroy(args):
    config = Config()

    git_ = run_wrapper('git', capture=True, check=False, print_error_as_ignored=True)
    git_("worktree remove --force %s" % config.dir)
    git_("branch -D %s" % config.pile_branch)


def parse_args(cmd_args):
    desc = """Manage a pile of patches on top of a git branch

git-pile helps to manage a long running and always changing list of patches on
top of git branch. It is similar to quilt, but aims to retain the git work flow
exporting the final result as a branch.

There are 3 important branches to understand how to use git-pile:

    BASE_BRANCH: where patches will be applied on top of.
    RESULT_BRANCH: the result of applying the patches on BASE_BRANCH
    PILE_BRANCH: where to keep the patches and track their history

This is a typical scenario git-pile is used in which BASE_BRANCH is "master"
and RESULT_BRANCH is "internal".

A---B---C master
         \\
          X---Y---Z internal

PILE_BRANCH is a branch containing this file hierarchy based on the above
example:

series  config  X.patch  Y.patch  Z.patch

The "series" and "config" file are there to allow git-pile to do its job
and are retained for compatibility with quilt and qf. git-pile exposes
commands to convert between RESULT_BRANCH and the files on PILE_BRANCH.
This allows to save the history of the patches when BASE_BRANCH changes
or patches are added, modified or removed on RESULT_BRANCH. Below is an
example in which the BASE_BRANCH evolves adding more commits:

A---B---C---D---E master
         \\
          X---Y---Z internal

After a rebase of the RESULT_BRANCH we will have the following state, in
which X', Y' and Z' denote the rebased patches. They may have possibly
changed to solve conflicts or to apply cleanly:

A---B---C---D---E master
                 \\
                  X'---Y'---Z' internal

In turn, PILE_BRANCH will store the saved result:

series  config  X'.patch  Y'.patch  Z'.patch
"""

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=desc)

    subparsers = parser.add_subparsers(title="Commands", dest="command")

    # init
    parser_init = subparsers.add_parser('init', help="Initialize configuration of git-pile in this repository")
    parser_init.add_argument(
        "-d", "--dir",
        help="Directory in which to place patches (default: %(default)s)",
        metavar="DIR",
        default="pile")
    parser_init.add_argument(
        "-p", "--pile-branch",
        help="Branch name to use for patches (default: %(default)s)",
        metavar="PILE_BRANCH",
        default="pile")
    parser_init.add_argument(
        "-b", "--base-branch",
        help="Base remote or local branch on top of which the patches from PILE_BRANCH should be applied (default: %(default)s)",
        metavar="BASE_BRANCH",
        default="master")
    parser_init.add_argument(
        "-r", "--result-branch",
        help="Branch to be created when applying patches from PILE_BRANCH on top of BASE_BRANCH (default: %(default)s",
        metavar="RESULT_BRANCH",
        default="internal")
    parser_init.set_defaults(func=cmd_init)

    # genpatches
    parser_genpatches = subparsers.add_parser('genpatches', help="Generate patches from BASE_BRANCH..RESULT_BRANCH and save to output directory")
    parser_genpatches.add_argument(
        "-o", "--output-directory",
        help="Use OUTPUT_DIR to store the resulting files instead of the DIR from the configuration. This must be an empty/non-existent directory unless -f/--force is also used",
        metavar="OUTPUT_DIR",
        default="")
    parser_genpatches.add_argument(
        "-f", "--force",
        help="Force use of OUTPUT_DIR even if it has patches. The existent patches will be removed.",
        action="store_true",
        default=False)
    parser_genpatches.add_argument(
        "commit_range",
        help="Commit range to use for the generated patches (default: BASE_BRANCH..RESULT_BRANCH)",
        metavar="COMMIT_RANGE",
        nargs="?",
        default="")
    parser_genpatches.set_defaults(func=cmd_genpatches)

    # destroy
    parser_destroy = subparsers.add_parser('destroy', help="Destroy all git-pile on this repo")
    parser_destroy.set_defaults(func=cmd_destroy)

    try:
        argcomplete.autocomplete(parser)
    except NameError:
        pass

    args = parser.parse_args(cmd_args)
    if not hasattr(args, "func"):
        parser.print_help()
        return None

    return args


def main(*cmd_args):
    args = parse_args(cmd_args)
    if not args:
        return 1

    return args.func(args)
