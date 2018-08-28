#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1+

import argparse
import os
import os.path as op
import shutil
import subprocess
import sys
import tempfile

from contextlib import contextmanager
from time import strftime

try:
    import argcomplete
except ImportError:
    pass

from .helpers import error, info, fatal
from .helpers import parse_raw_diff, run_wrapper


# external commands
git = run_wrapper('git', capture=True)

nul_f = open(os.devnull, 'w')


class Config:
    def __init__(self):
        self.dir = ""
        self.result_branch = ""
        self.pile_branch = ""

        s = git(["config", "--get-regex", "pile\\.*"], check=False, stderr=nul_f).stdout.strip()
        if not s:
            return

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

    def revert(self, other):
        if not other.is_valid():
            self.destroy()

        self.dir = other.dir
        if self.dir:
            git("config pile.dir %s" % self.dir)

        self.result_branch = other.result_branch
        if self.result_branch:
            git("config pile.result-branch %s" % self.result_branch)

        self.pile_branch = other.pile_branch
        if self.pile_branch:
            git("config pile.pile-branch %s" % self.pile_branch)


    def destroy(self):
        git("config --remove-section pile", check=False, stderr=nul_f, stdout=nul_f)


def git_branch_exists(branch):
    return git("show-ref --verify --quiet refs/heads/%s" % branch, check=False).returncode == 0


# Return the toplevel directory of the outermost git root, i.e. even if you are in a worktree
# checkout it will return the "main" directory. E.g:
#
# $ git worktree list
# /tmp/git-pile-playground          9f6f8b4 [internal]
# /tmp/git-pile-playground/patches  f7672c2 [pile]
#
# If CWD is any of those directories, git_root() will return the topmost:
# /tmp/git-pile-playground
#
# It works when we have a .git dir inside a work tree, but not in the rare cases of
# having a gitdir detached from the worktree
def git_root():
    commondir = git("rev-parse --git-common-dir").stdout.strip("\n")
    return git("-C %s rev-parse --show-toplevel" % op.join(commondir, "..")).stdout.strip("\n")


def git_worktree_get_checkout_path(root, branch):
    state = dict()
    out = git("-C %s worktree list --porcelain" % root).stdout.split("\n")

    for l in out:
        if not l:
            # end block
            if state.get("branch", None) == "refs/heads/" + branch:
                return state["worktree"]

            state = dict()
            continue

        v = l.split(" ")
        state[v[0]] = v[1] if len(v) > 1 else None

    return None


def get_baseline(d):
    with open(op.join(d, "config"), "r") as f:
        for l in f:
            if l.startswith("BASELINE="):
                baseline = l[9:].strip()
                return baseline

    return None


def update_baseline(d, commit):
    with open(op.join(d, "config"), "w") as f:
        rev = git("rev-parse %s" % commit).stdout.strip()
        f.write("BASELINE=%s" % rev)


# Create a temporary directory to checkout a detached branch with git-worktree
# making sure it gets deleted (both the directory and from git-worktree) when
# we finished using it.
#
# To be used in `with` context handling.
@contextmanager
def temporary_worktree(commit, dir, prefix=".git-pile-worktree"):
    try:
        with tempfile.TemporaryDirectory(dir=dir, prefix=prefix) as d:
            git("worktree add --detach --checkout %s %s" % (d, commit),
                stdout=nul_f, stderr=nul_f)
            yield d
    finally:
        git("worktree remove %s" % d)


def cmd_init(args):
    try:
        base_commit = git("rev-parse %s" % args.baseline, stderr=nul_f).stdout.strip()
    except subprocess.CalledProcessError:
        fatal("invalid baseline commit %s" % args.baseline)

    path = git_worktree_get_checkout_path(git_root(), args.pile_branch)
    if path:
        fatal("branch '%s' is already checked out at '%s'" % (args.pile_branch, path))

    if (op.exists(args.dir)):
        fatal("'%s' already exists" % args.dir)

    oldconfig = Config()

    git("config pile.dir %s" % args.dir)
    git("config pile.pile-branch %s" % args.pile_branch)
    git("config pile.result-branch %s" % args.result_branch)

    config = Config()

    if not git_branch_exists(config.pile_branch):
        info("Creating branch %s" % config.pile_branch)

        # Create and an orphan branch named `config.pile_branch` at the
        # `config.dir` location. Unfortunately git-branch can't do that;
        # git-checkout has a --orphan option, but that would necessarily
        # checkout the branch and the user would be left wondering what
        # happened if any command here on fails.
        #
        # Workaround is to do that ourselves with a temporary repository
        with tempfile.TemporaryDirectory() as d:
            git("-C %s init" % d)
            update_baseline(d, base_commit)
            git("-C %s add -A" % d)
            git(["-C", d, "commit", "-m", "Initial git-pile configuration"])

            # Temporary repository created, now let's fetch and create our branch
            git("fetch %s master:%s" % (d, config.pile_branch), stdout=nul_f, stderr=nul_f)


    # checkout pile branch as a new worktree
    try:
        git("worktree add --checkout %s %s" % (config.dir, config.pile_branch),
            stdout=nul_f, stderr=nul_f)
    except:
        config.revert(oldconfig)
        fatal("failed to checkout worktree at %s" % config.dir)

    if oldconfig.is_valid():
        info("Reinitialized existing git-pile's branch '%s' in '%s/'" %
             (config.pile_branch, config.dir), color=False)
    else:
        info("Initialized empty git-pile's branch '%s' in '%s/'" %
             (config.pile_branch, config.dir), color=False)

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


def parse_commit_range(commit_range, pile_dir, default_end):
    if not commit_range:
        baseline = get_baseline(pile_dir)
        if not baseline:
            fatal("no BASELINE configured in %s" % config.dir)
        return baseline, default_end

    # sanity checks
    try:
        base, result = commit_range.split("..")
        git("rev-parse %s" % base, stderr=nul_f, stdout=nul_f)
        git("rev-parse %s" % result, stderr=nul_f, stdout=nul_f)
    except (ValueError, subprocess.CalledProcessError) as e:
        fatal("Invalid commit range: %s" % commit_range)

    return base, result


def get_series_linenum_dict(d):
    series = dict()
    with open(op.join(d, "series"), "r") as f:
        linenumber = 0
        for l in f:
            series[l[:-1]] = linenumber
            linenumber += 1

    return series


# pre-existent patches are removed, all patches written from commit_range,
# "config" and "series" overwritten with new valid content
def genpatches(output, base_commit, result_commit):
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

    commit_range = "%s..%s" % (base_commit, result_commit)
    commit_list = git("rev-list --reverse %s" % commit_range).stdout.strip().split('\n')
    if not commit_list:
        fatal("No commits in range %s" % commit_range)

    # Do everything in a temporary directory and once we know it went ok, move
    # to the final destination - we can use os.rename() since we are creating
    # the directory and using a subdir as staging
    with tempfile.TemporaryDirectory() as d:
        staging = op.join(d, "staging")
        series = []
        for c in commit_list:
            path_orig = git(["format-patch", "--subject-prefix=PATCH", "--zero-commit", "--signature=",
                             "-o", staging, "-N", "-1", c]).stdout.strip()
            path = fix_duplicate_patch_name(d, path_orig, len(commit_list))
            os.rename(path_orig, path)
            series.append(path)

        os.rmdir(staging)

        os.makedirs(output, exist_ok=True)
        rm_patches(output)

        for p in series:
            s = shutil.copy(p, output)

    with open(op.join(output, "series"), "w") as f:
        f.write("# Auto-generated by git-pile\n\n")
        for s in series:
            f.write(op.basename(s))
            f.write("\n")

    update_baseline(output, base_commit)

    return 0


def gen_cover_letter(diff, output, n_patches, baseline, prefix):
    user = git("config --get user.name").stdout.strip()
    email = git("config --get user.email").stdout.strip()
    # RFC 2822-compliant date format
    now = strftime("%a, %d %b %Y %T %z")

    cover = op.join(output, "0000-cover-letter.patch")
    with open(cover, "w") as f:
        f.write("""From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001
From: {user} <{email}>
Date: {date}
Subject: [{prefix} 0/{n_patches}] *** SUBJECT HERE ***
MIME-Version: 1.0
Content-Type: text/plain; charset=UTF-8
Content-Transfer-Encoding: 8bit

*** BLURB HERE ***

---
Changes below are based on current pile tree with
BASELINE={baseline}

""".format(user=user, email=email, date=now, n_patches=n_patches, baseline=baseline, prefix=prefix))
        for l in diff:
            f.write(l)

    return cover


def cmd_genpatches(args):
    config = Config()
    if not config.check_is_valid():
        return 1

    base, result = parse_commit_range(args.commit_range, config.dir,
                                      config.result_branch)

    # Be a little careful here: the user might have passed e.g. /tmp: we
    # don't want to remove patches there to avoid surprises
    if args.output_directory != "":
        output = args.output_directory
        if has_patches(output) and not args.force:
            fatal("'%s' is not default output directory and has patches in it.\n"
                  "Force with --force or pass an empty/non-existent directory" % output)
    else:
        output = config.dir

    return genpatches(output, base, result)


def cmd_format_patch(args):
    config = Config()
    if not config.check_is_valid():
        return 1

    # Allow the user to name the topic/feature branch as they please:
    # default to whatever the HEAD is
    # default to baseline..HEAD
    base, result = parse_commit_range(args.commit_range, config.dir, "HEAD")

    with temporary_worktree(config.pile_branch, git_root()) as tmpdir:
        ret = genpatches(tmpdir, base, result)
        if ret != 0:
            return 1

        git("-C %s add -A" % tmpdir)
        baseline = get_baseline(config.dir)
        order_file = op.join(op.dirname(op.realpath(__file__)),
                             "data", "git-cover-order.txt")

        with subprocess.Popen(["git", "-C", tmpdir, "diff", "--cached", "-p", "--raw", '-O', order_file ],
                              stdout=subprocess.PIPE, universal_newlines=True) as proc:
            # get a list of (state, new_name) tuples
            changed_files = parse_raw_diff(proc.stdout)
            # and finish reading all the diff
            diff = proc.stdout.readlines()
            if not diff:
                fatal("Nothing changed from %s..%s to %s..%s"
                      % (baseline, config.result_branch, base, result))
       
        patches = []
        for action, fn in changed_files:
            # deleted files will appear in the series file diff, we can skip them here
            if action == 'D':
                continue

            # only collect the patch files
            if not fn.endswith(".patch"):
                continue

            if action not in "RACMT":
                fatal("Unknown state in diff '%s' for file '%s'" % (action, fn))

            patches.append(fn)

        series = get_series_linenum_dict(tmpdir)
        patches.sort(key=lambda p: series.get(p, 0))

        # From here on, use the real directory
        output = args.output_directory
        os.makedirs(output, exist_ok=True)
        rm_patches(output)

        try:
            prefix = git("config --get format.subjectprefix").stdout.strip()
        except subprocess.CalledProcessError:
            prefix = "PATCH"

        cover = gen_cover_letter(diff, output, len(patches), baseline, prefix)
        print(cover)

        for i, p in enumerate(patches):
            old = op.join(tmpdir, p)
            new = op.join(output, "%04d-%s" % (i + 1, p[5:]))

            # Copy patches to the final output direcory fixing the Subject
            # lines to conform with the patch order and prefix
            with open(old, "r") as oldf:
                with open(new, "w") as newf:
                    # parse header
                    subject_header = "Subject: [PATCH] "
                    for l in oldf:
                        if l == "\n":
                            # header end, give up, don't try to parse the body
                            fatal("patch '%s' missing subject?" % old)
                        if not l.startswith(subject_header):
                            # header line != subject, just copy it
                            newf.write(l)
                            continue

                        # found the subject, re-format it
                        title = l[len(subject_header):]
                        newf.write("Subject: [{prefix} {i}/{n_patches}] {title}".format(
                                   prefix=prefix, i=i + 1, n_patches=len(patches),
                                   title=title))
                        break
                    else:
                        fatal("patch '%s' missing subject?" % old)

                    # write all the other lines after Subject header at once
                    newf.writelines(oldf.readlines())

            print(new)

    return 0

def cmd_genbranch(args):
    config = Config()
    if not config.check_is_valid():
        return 1

    branch = args.branch if args.branch else config.result_branch
    root = git_root()
    patchesdir = op.join(root, config.dir)
    baseline = get_baseline(patchesdir)

    patches = []
    with open(op.join(patchesdir, "series"), "r") as f:
        for l in f:
            l = l.strip()
            if not l or l.startswith("#"):
                continue

            p = op.join(patchesdir, l)
            if not op.isfile(p):
                fatal("series file reference '%s', but it doesn't exist" % p)

            patches.append(p)

    # work in a separate directory to avoid cluttering whatever the user is doing
    # on the main one
    with temporary_worktree(baseline, root) as d:
        for p in patches:
            if args.verbose:
                print(p)
            git("-C %s am %s" % (d, op.join(patchesdir, p)))

        # always save HEAD to PILE_RESULT_HEAD
        shutil.copyfile(op.join(root, ".git", "worktrees", op.basename(d), "HEAD"),
                        op.join(root, ".git", "PILE_RESULT_HEAD"))

        path = git_worktree_get_checkout_path(root, branch)
        if path:
            error("final result is PILE_RESULT_HEAD but branch '%s' could not be updated to it "
                  "because it is checked out at '%s'" % (branch, path))
            return 1

        git("-C %s checkout -B %s HEAD" % (d, branch), stdout=nul_f, stderr=nul_f)

    return 0


# Temporary command to help with development
def cmd_destroy(args):
    config = Config()

    git_ = run_wrapper('git', capture=True, check=False, print_error_as_ignored=True)
    if config.dir:
        git_("worktree remove --force %s" % config.dir)
    git_("branch -D %s" % config.pile_branch)

    # implode
    git_("config --remove-section pile")


def parse_args(cmd_args):
    desc = """Manage a pile of patches on top of a git branch

git-pile helps to manage a long running and always changing list of patches on
top of git branch. It is similar to quilt, but aims to retain the git work flow
exporting the final result as a branch. The end result is a configuration setup
that can still be used with it.

There are 2 branches and one commit head that are important to understand how
git-pile works:

    PILE_BRANCH: where to keep the patches and track their history
    RESULT_BRANCH: the result of applying the patches on top of (changing) base

The changing base is a commit that continues to be updated (either as a fast-forward
or as non-ff) onto where we want to be based off. This changing head is here
called BASELINE.

    BASELINE: where patches will be applied on top of.

This is a typical scenario git-pile is used in which BASELINE currently points
to a "master" branch and RESULT_BRANCH is "internal" (commit hashes here
onwards are fictitious).

A---B---C 3df0f8e (master)
         \\
          X---Y---Z internal

PILE_BRANCH is a branch containing this file hierarchy based on the above
example:

series  config  X.patch  Y.patch  Z.patch

The "series" and "config" files are there to allow git-pile to do its job and
are retained for compatibility with quilt and qf. For that reason the latter is
also where BASELINE is stored/read when it's needed. git-pile exposes commands
to convert back and forth between RESULT_BRANCH and the files on PILE_BRANCH.
Those commands allows to save the history of the patches when the BASELINE
changes or patches are added, modified or removed in RESULT_BRANCH. Below is a
example in which BASELINE may evolve to add more commit from upstream:

          D---E master
         /
A---B---C 3df0f8e
         \\
          X---Y---Z internal

After a rebase of the RESULT_BRANCH we will have the following state, in
which X', Y' and Z' denote the rebased patches. They may have possibly
changed to solve conflicts or to apply cleanly:

A---B---C---D---E 76bc046 (master)
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
        default="patches")
    parser_init.add_argument(
        "-p", "--pile-branch",
        help="Branch name to use for patches (default: %(default)s)",
        metavar="PILE_BRANCH",
        default="pile")
    parser_init.add_argument(
        "-b", "--baseline",
        help="Baseline commit on top of which the patches from PILE_BRANCH should be applied (default: %(default)s)",
        metavar="BASELINE",
        default="master")
    parser_init.add_argument(
        "-r", "--result-branch",
        help="Branch to be created when applying patches from PILE_BRANCH on top of BASELINE (default: %(default)s",
        metavar="RESULT_BRANCH",
        default="internal")
    parser_init.set_defaults(func=cmd_init)

    # genpatches
    parser_genpatches = subparsers.add_parser('genpatches', help="Generate patches from BASELINE..RESULT_BRANCH and save to output directory")
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
        help="Commit range to use for the generated patches (default: BASELINE..RESULT_BRANCH)",
        metavar="COMMIT_RANGE",
        nargs="?",
        default="")
    parser_genpatches.set_defaults(func=cmd_genpatches)

    # genbranch
    parser_genbranch = subparsers.add_parser('genbranch', help="Generate RESULT_BRANCH by applying patches from PILE_BRANCH on top of BASELINE")
    parser_genbranch.add_argument(
        "-b", "--branch",
        help="Use BRANCH to store the final result instead of RESULT_BRANCH",
        metavar="BRANCH",
        default="")
    parser_genbranch.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False)
    parser_genbranch.set_defaults(func=cmd_genbranch)

    # format-patch
    parser_format_patch = subparsers.add_parser('format-patch', help="Generate patches from BASELINE..HEAD and save patch series to output directory to be shared on a mailing list")
    parser_format_patch.add_argument(
        "-o", "--output-directory",
        help="Use OUTPUT_DIR to store the resulting files instead of the CWD. This must be an empty/non-existent directory unless -f/--force is also used",
        metavar="OUTPUT_DIR",
        default="")
    parser_format_patch.add_argument(
        "-f", "--force",
        help="Force use of OUTPUT_DIR even if it has patches. The existent patches will be removed.",
        action="store_true",
        default=False)
    parser_format_patch.add_argument(
        "commit_range",
        help="Commit range to use for the generated patches (default: BASELINE..HEAD)",
        metavar="COMMIT_RANGE",
        nargs="?",
        default="")
    parser_format_patch.set_defaults(func=cmd_format_patch)

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
