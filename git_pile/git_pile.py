#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1+

import argparse
import email
import email.header
import math
import os
import os.path as op
import shutil
import subprocess
import sys
import tempfile
import timeit

from contextlib import contextmanager, redirect_stdout, redirect_stderr
from time import strftime

from .helpers import error, info, fatal, warn
from .helpers import run_wrapper, orderedset, open_or_stdin, prompt_yesno, pushdir
from .helpers import set_debugging, set_fatal_behavior
from . import __version__

try:
    import argcomplete
except ImportError:
    warn("can't find python3-argcomplete: argument completion won't be available")
    pass


# external commands
git = run_wrapper('git', capture=True)
git_can_fail = run_wrapper('git', capture=True, check=False)

nul_f = open(os.devnull, 'w')

def log10_or_zero(n):
    return math.log10(n) if n else 0

def assert_required_tools():
    error_msg_git = "git >= 2.19 is needed, please check requirements"

    # We need git range-diff from git >= 2.19. Instead of checking the version, let's try to check
    # the feature we are interested in. We also have other requirements for using this version
    # like worktree working properly. However that should be available on any version that has
    # range-diff.
    try:
        exec_path = git("--exec-path").stdout.strip()
    except subprocess.CalledProcessError:
        fatal(error_msg_git)

    path = os.getenv("PATH") + ":" + exec_path
    if not shutil.which("git-range-diff", path=path):
        # Let's be resilient to weird installations not having the symlink in place.
        # For some reason "git range-diff -h" returns 129 rather than the usual 0
        # ¯\_(ツ)_/¯
        if git("range-diff -h", check=False, capture=False, stderr=nul_f).returncode != 129:
            fatal(error_msg_git)


class Config:
    def __init__(self):
        self.dir = ""
        self.result_branch = ""
        self.pile_branch = ""
        self.format_add_header = ""
        self.format_output_directory = ""
        self.linear_branch = ""
        self.genbranch_committer_date_is_author_date = True
        self.genbranch_user_name = None
        self.genbranch_user_email = None

        s = git(["config", "--get-regexp", "^pile\\.*"], check=False, stderr=nul_f).stdout.strip()
        if not s:
            return

        for kv in s.split('\n'):
            try:
                key, value = kv.strip().split(maxsplit=1, sep=" ")
            except ValueError:
                key = kv
                value = None

            # pile.*
            key = key[5:].translate(str.maketrans('-.', '__'))
            try:
                if hasattr(self, key) and isinstance(getattr(self, key), bool):
                    value = self._value_to_bool(value)

                setattr(self, key, value)
            except:
                warn(f"could not set {key}={value} from git config")

    def _value_to_bool(self, value):
        return value is None or value.lower() in [ "yes", "on", "true", "1" ]

    def is_valid(self):
        return self.dir != '' and self.result_branch != '' and self.pile_branch != ''

    def check_is_valid(self):
        if not self.is_valid():
            error("git-pile configuration is not valid. Configure it first with 'git pile init' or 'git pile setup'")
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


def git_ref_exists(ref):
    return git(f"show-ref --verify --quiet {ref}", check=False).returncode == 0


def git_remote_branch_exists(remote_and_branch):
    return git("show-ref --verify --quiet refs/remotes/%s" % remote_and_branch, check=False).returncode == 0


def git_init(branch, directory):
    if git_can_fail(f"-C {directory} init -b {branch}", stderr=nul_f).returncode == 0:
        return

    # git-init in git < 2.28 doesn't have a -b switch. Try to do that ourselves
    git(f"-C {directory} init")
    git(f"-C {directory} checkout -b {branch}")


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


# Return the path a certain branch is checked out at
# or None.
def git_worktree_get_checkout_path(root, branch):
    state = dict()
    out = git("-C %s worktree list --porcelain" % root).stdout.split("\n")
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
def git_worktree_get_git_dir(path='.'):
    return git("-C %s rev-parse --git-dir" % path).stdout.strip("\n")


@contextmanager
def git_split_index(path='.'):
    # only change if not explicitely configure in config
    change_split_index = git_can_fail(f'-C {path} config --get core.splitIndex').returncode != 0

    if not change_split_index:
        try:
            yield
        finally:
            return

    change_shared_index_expire = git_can_fail(f'-C {path} config --get splitIndex.sharedIndexExpire').returncode != 0

    try:
        git(f'-C {path} update-index --split-index')
        if change_shared_index_expire:
            git(f'-C {path} config splitIndex.sharedIndexExpire now')

        yield
    finally:
        git(f'-C {path} update-index --no-split-index')
        if change_shared_index_expire:
            git(f'-C {path} config --unset splitIndex.sharedIndexExpire')


def _parse_baseline_line(iterable):
    for l in iterable:
        if l.startswith("BASELINE="):
            baseline = l[9:].strip()
            return baseline
    return None


def get_baseline_from_branch(branch):
    out = git("show %s:config --" % branch).stdout
    return _parse_baseline_line(out.splitlines())


def get_baseline(d):
    with open(op.join(d, "config"), "r") as f:
        return _parse_baseline_line(f)


def update_baseline(d, commit):
    with open(op.join(d, "config"), "w") as f:
        rev = git("rev-parse %s" % commit).stdout.strip()
        f.write("BASELINE=%s" % rev)


def update_series(d, series_list):
    with open(op.join(d, "series"), "w") as f:
        f.write("# Auto-generated by git-pile\n\n")
        f.write('\n'.join(series_list))
        f.write('\n')


# Both branch and remote can contain '/' so we can't disambiguate it
# unless we go through the list of remotes. This takes an argument
# like "origin/master", "myfork/wip", etc and return the branch name
# stripping the remote prefix, i.e. "master" and "wip" respectively.
# If no branch was found None is returned, which means that although
# it looks like a remote/branch pair, it is not.
def get_branch_from_remote_branch(remote_branch):
    out = git("remote").stdout
    for l in out.splitlines():
        if remote_branch.startswith(l):
            return remote_branch[len(l) + 1:]
    return None


def assert_valid_pile_branch(pile):
    # --full-tree is necessary so we don't need "-C gitroot"
    out = git("ls-tree -r --name-only --full-tree %s" % pile).stdout
    has_config = False
    has_series = False
    non_patches = False

    for l in out.splitlines():
        if l == "config":
            has_config = True
        elif l == "series":
            has_series = True
        elif not l.endswith(".patch") and not l.startswith('.') and op.dirname(l) != '':
            non_patches = True

    errorstr = "Branch '{pile}' does not look like a pile branch. No '{filename}' file found."
    if not has_series:
        fatal(errorstr.format(pile=pile, filename="series"))
    if not has_config:
        fatal(errorstr.format(pile=pile, filename="config"))
    if non_patches:
        warn("Branch '{pile}' has non-patch files".format(pile=pile))


def assert_valid_result_branch(result_branch, baseline):
    try:
        git("rev-parse %s" % baseline, stderr=nul_f)
    except subprocess.CalledProcessError:
        fatal("invalid baseline commit %s" % baseline)

    try:
        out = git("merge-base %s %s" % (baseline, result_branch)).stdout.strip()
    except subprocess.CalledProcessError:
        out = None

    if out != baseline:
        fatal("branch '%s' does not contain baseline %s" % (result_branch, baseline))


# Create a temporary directory to checkout a detached branch with git-worktree
# making sure it gets deleted (both the directory and from git-worktree) when
# we finished using it.
#
# To be used in `with` context handling.
@contextmanager
def temporary_worktree(commit, dir, prefix="git-pile-worktree"):
    class Break(Exception):
      """Break out of the with statement"""

    try:
        with tempfile.TemporaryDirectory(dir=dir, prefix=prefix) as d:
            git("worktree add --detach --checkout %s %s" % (d, commit),
                stdout=nul_f, stderr=nul_f)
            yield d
    finally:
        git("worktree remove %s" % d)


def cmd_init(args):
    assert_required_tools()

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

        # Create an orphan branch named `config.pile_branch` at the
        # `config.dir` location. Unfortunately git-branch can't do that;
        # git-checkout has a --orphan option, but that would necessarily
        # checkout the branch and the user would be left wondering what
        # happened if any command here on fails.
        #
        # Workaround is to do that ourselves with a temporary repository
        with tempfile.TemporaryDirectory() as d:
            git_init("pile", d)
            update_baseline(d, base_commit)
            git("-C %s add -A" % d)
            git(["-C", d, "commit", "-m", "Initial git-pile configuration"])

            # Temporary repository created, now let's fetch and create our branch
            git("fetch %s pile:%s" % (d, config.pile_branch), stdout=nul_f, stderr=nul_f)


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


def cmd_setup(args):
    assert_required_tools()

    create_pile_branch = True
    create_result_branch = True

    if git_remote_branch_exists(args.pile_branch):
        local_pile_branch = get_branch_from_remote_branch(args.pile_branch)
        if git_branch_exists(local_pile_branch):
            # allow case that e.g. 'origin/pile' and 'pile' point to the same commit
            if git("rev-parse %s" % args.pile_branch).stdout == git("rev-parse %s" % local_pile_branch).stdout:
                create_pile_branch = False
            elif not args.force:
                fatal("using '%s' for pile but branch '%s' already exists and point elsewhere" % (args.pile_branch, local_pile_branch))
    elif git_branch_exists(args.pile_branch):
        local_pile_branch = args.pile_branch
        create_pile_branch = False
    else:
        fatal("Branch '%s' does not exist neither as local or remote branch" % args.pile_branch)

    # optional arg: use current branch that is checked out in git_root()
    gitroot = git_root()
    try:
        result_branch = args.result_branch if args.result_branch else git('-C %s symbolic-ref --short -q HEAD' % gitroot).stdout.strip()
    except subprocess.CalledProcessError:
        fatal("no argument passed for result branch and no branch is currently checkout at '%s'" % gitroot)

    # same as for pile branch but allow for non-existent result branch, we will just create one
    if git_remote_branch_exists(result_branch):
        local_result_branch = get_branch_from_remote_branch(result_branch)
        if git_branch_exists(local_result_branch):
            # allow case that e.g. 'origin/internal' and 'internal' point to the same commit
            if git("rev-parse %s" % result_branch).stdout == git("rev-parse %s" % local_result_branch).stdout:
                create_result_branch = False
            elif not args.force:
                fatal("using '%s' for result but branch '%s' already exists and point elsewhere" % (result_branch, local_result_branch))
    elif git_branch_exists(result_branch):
        local_result_branch = result_branch
        create_result_branch = False
    else:
        local_result_branch = git('-C %s symbolic-ref --short -q HEAD' % gitroot).stdout.strip()
        create_result_branch = False

    # content of the pile branch looks like a pile branch?
    assert_valid_pile_branch(args.pile_branch)
    baseline = get_baseline_from_branch(args.pile_branch)

    # sane result branch wrt baseline configured?
    assert_valid_result_branch(result_branch, baseline)

    path = git_worktree_get_checkout_path(gitroot, local_pile_branch)
    patchesdir = op.join(gitroot, args.dir)
    if path:
        # if pile branch is already checked out, it must be in the same
        # patchesdir on where we are trying to configure.
        if path != patchesdir:
            fatal("branch '%s' is already checked out at '%s'"
                  % (local_pile_branch, path))
        need_worktree = False
    else:
        # no checkout of pile branch. One more sanity check: the dir doesn't
        # exist yet, otherwise we could clutter whatever the user has there.
        if (op.exists(patchesdir)):
            fatal("'%s' already exists" % args.dir)
        need_worktree = True

    path = git_worktree_get_checkout_path(gitroot, local_result_branch)
    if path and path != gitroot:
        fatal("branch '%s' is already checked out at '%s'"
              % (local_result_branch, path))

    force_arg = "-f" if args.force else ""
    # Yay, it looks like all sanity checks passed and we are not being
    # fuzzy-tested, try to do the useful work
    if create_pile_branch:
        info("Creating branch %s" % local_pile_branch)
        git("branch %s -t %s %s" % (force_arg, local_pile_branch, args.pile_branch))
    if create_result_branch:
        info("Creating branch %s" % local_result_branch)
        if not path:
            git("branch %s -t %s %s" % (force_arg, local_result_branch, result_branch))
        else:
            git("-C %s reset --hard %s" % (path, result_branch), stdout=nul_f, stderr=nul_f)


    if need_worktree:
        # checkout pile branch as a new worktree
        try:
            git("-C %s worktree add --checkout %s %s" % (gitroot, args.dir, local_pile_branch),
                stdout=nul_f, stderr=nul_f)
        except:
            fatal("failed to checkout worktree for '%s' at %s" % (local_pile_branch, args.dir))

    # write down configuration
    git("config pile.dir %s" % args.dir)
    git("config pile.pile-branch %s" % local_pile_branch)
    git("config pile.result-branch %s" % local_result_branch)

    tracked_pile = git("rev-parse --abbrev-ref %s@{u}" % local_pile_branch,
                       check=False).stdout
    if tracked_pile:
        tracked_pile = " (tracking %s)" % tracked_pile.strip()
    tracked_result = git("rev-parse --abbrev-ref %s@{u}" % local_result_branch,
                         check=False).stdout
    if tracked_result:
        tracked_result = " (tracking %s)" % tracked_result.strip()

    info("Pile branch '%s'%s setup successfully to generate branch '%s'%s" %
         (local_pile_branch, tracked_pile, local_result_branch, tracked_result),
         color=False)

    return 0


def fix_duplicate_patch_names(patches):
    # quick check and return
    if len(set(patches)) == len(patches):
        return patches

    # deduplicate
    ret = []
    max_retries = len(patches) + 2
    for p in patches:
        newp = p
        retry = 2
        while newp in ret:
            if retry > max_retries:
                raise Exception("wat!?! '%s' (max_retries=%d)" % (p, max_retries))
            newp = p + "-%d" % retry
            retry += 1

        ret.append(newp)
    return ret


def generate_series_list(commit_range, suffix):
    if ".." in commit_range:
        single_arg = []
    else:
        single_arg = ["-1"]

    series = git(["log", "--format=%f", "--reverse", *single_arg, commit_range]).stdout.strip().split("\n")
    # truncate name as per output of git-format-patch
    series = [x[0:52] for x in series]
    series = fix_duplicate_patch_names(series)
    # add 0001 and .patch prefix/suffix
    series = ["0001-{name}{suffix}".format(name=x, suffix=suffix) for x in series]

    return series if not single_arg else series[0]


def rm_patches(dest):
    for entry in os.scandir(dest):
        if not entry.is_file() or not entry.name.endswith(".patch"):
            continue

        try:
            os.remove(entry.path)
        except PermissionError:
            fatal("Could not remove %s: permission denied" % entry.path)


def has_patches(dest):
    try:
        dir = os.scandir(dest)
        for entry in dir:
            if entry.is_file() and entry.name.endswith(".patch"):
                dir.close()
                return True
    except FileNotFoundError:
        pass

    return False


def parse_commit_range(commit_range, pile_dir, default_end):
    if not commit_range:
        baseline = get_baseline(pile_dir)
        if not baseline:
            fatal("no BASELINE configured in %s" % pile_dir)
        return baseline, default_end

    range = commit_range.split("..")
    if len(range) == 1:
        range.append("HEAD")
    elif range[0] == "":
        fatal("Invalid commit range '%s'" % commit_range)
    elif range[1] == "":
        range[1] = "HEAD"
    base, result = range
    # sanity checks
    try:
        git("rev-parse %s" % base, stderr=nul_f, stdout=nul_f)
        git("rev-parse %s" % result, stderr=nul_f, stdout=nul_f)
    except (ValueError, subprocess.CalledProcessError) as e:
        fatal("Invalid commit range: %s" % commit_range)

    return base, result


def copy_sanitized_patch(p, pnew):
    with open(p, "r") as oldf:
        with open(pnew, "w") as newf:
            it = iter(oldf)

            # everything before the diff is allowed
            for l in it:
                newf.write(l)
                if l == "---\n":
                    break
            else:
                fatal("malformed patch %s\n" % p)

            # any additional patch context (like stat) is allowed
            for l in it:
                newf.write(l)
                if l.startswith("diff --git"):
                    break
            else:
                fatal("malformed patch %s\n" % p)


            while True:
                # hunk header: everything but "index lines" are allowed,
                # except if we are in a binary patch: in that case the
                # index must be maintained otherwise it's not possible to
                # reconstruct the branch
                hunk_header = []
                index_line = -1
                is_binary = False
                for l in it:
                    hunk_header.append(l)
                    if l.startswith("@@"):
                        break
                    if l.startswith("GIT binary patch"):
                        is_binary = True
                        break
                    if l.startswith("index"):
                        index_line = len(hunk_header) - 1

                if not is_binary and index_line >= 0:
                    hunk_header.pop(index_line)

                newf.writelines(hunk_header)

                for l in it:
                    newf.write(l)
                    if l.startswith("diff --git"):
                        break
                else:
                    # EOF, break outer loop
                    break


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

    series = generate_series_list(commit_range, ".patch")

    # Do everything in a temporary directory and once we know it went ok, move
    # to the final destination - we can use os.rename() since we are creating
    # the directory and using a subdir as staging
    with tempfile.TemporaryDirectory() as d:
        proc = git(["format-patch", "--no-add-header", "--no-cc", "--subject-prefix=PATCH",
                    "--zero-commit", "--signature=", "-N", '-o', d, commit_range])

        patches = proc.stdout.strip().splitlines()

        os.makedirs(output, exist_ok=True)
        rm_patches(output)

        for pold, pnew in zip(patches, series):
            copy_sanitized_patch(pold, op.join(output, pnew))

    update_series(output, series)
    update_baseline(output, base_commit)

    return 0


def get_cover_letter_message(commit_with_message, file_with_message, signoff):
    if file_with_message:
        with open_or_stdin(file_with_message, "r") as f:
            subject = f.readline().strip()
            body = "".join(f.readlines()).strip()
    elif commit_with_message:
        subject = git(["log", "--format=%s", "-1", commit_with_message]).stdout.strip()
        body = git(["log", "--format=%b",  "-1", commit_with_message]).stdout.strip()
    else:
        subject = "*** SUBJECT HERE ***"
        body = "*** BLURB HERE ***"

    if signoff:
        user = git("config --get user.name").stdout.strip()
        email = git("config --get user.email").stdout.strip()
        body += f"\n\nSigned-off-by: {user} <{email}>"

    return subject, body


def gen_cover_letter(diff, output, n_patches, baseline, pile_commit, prefix, range_diff_commits, add_header, subject, body):
    user = git("config --get user.name").stdout.strip()
    email = git("config --get user.email").stdout.strip()
    # RFC 2822-compliant date format
    now = strftime("%a, %d %b %Y %T %z")

    # 1:  34cf518f0aab ! 1:  3a4e12046539 <commit message>
    # Let only the lines with state == !, < or >
    reduced_range_diff = "\n".join(list(filter(lambda x: x and x.split(maxsplit=3)[2] in "!><", range_diff_commits)))

    zero_fill = int(log10_or_zero(n_patches)) + 1
    with open(output, "w") as f:
        f.write("""From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001
From: {user} <{email}>
Date: {date}
Subject: [{prefix} {zeroes}/{n_patches}] {subject}
MIME-Version: 1.0
Content-Type: text/plain; charset=UTF-8
Content-Transfer-Encoding: 8bit{add_header}

{body}
---
baseline: {baseline}
pile-commit: {pile_commit}
range-diff:
{range_diff}

""".format(user=user, email=email, date=now, zeroes="0".zfill(zero_fill),
           n_patches=n_patches, baseline=baseline, pile_commit=pile_commit, prefix=prefix,
           range_diff=reduced_range_diff, add_header="\n" + add_header if add_header else "",
           subject=subject, body=body))

        for l in diff:
            f.write(l)

        f.write("--\ngit-pile {version}\n\n".format(version=__version__))


def gen_full_tree_patch(output, n_patches, oldbaseline, newbaseline, oldref, newref, prefix, add_header):
    user = git("config --get user.name").stdout.strip()
    email = git("config --get user.email").stdout.strip()
    # RFC 2822-compliant date format
    now = strftime("%a, %d %b %Y %T %z")

    with open(output, "w") as f:
        f.write("""From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001
From: {user} <{email}>
Date: {date}
Subject: [{prefix} {n_patches}/{n_patches}] REVIEW: Full tree diff against {oldref}
MIME-Version: 1.0
Content-Type: text/x-patch; charset=UTF-8
Content-Transfer-Encoding: 8bit{add_header}

Auto-generated diff between {oldref}..{newref}
---
""".format(user=user, email=email, date=now, oldref=oldref, newref=newref,
           prefix = prefix, n_patches = n_patches,
           add_header="\n" + add_header if add_header else ""))

        f.flush()
        git("diff --stat -p --no-ext-diff {oldref}..{newref}".format(oldref=oldref, newref=newref), stdout=f)
        f.flush()

        f.write("--\ngit-pile {version}\n\n".format(version=__version__))


def cmd_genpatches(args):
    config = Config()
    if not config.check_is_valid():
        return 1

    root = git_root()
    patchesdir = op.join(root, config.dir)
    base, result = parse_commit_range(args.commit_range, patchesdir,
                                      config.result_branch)

    commit_result = args.commit_result or args.message is not None

    # Be a little careful here: the user might have passed e.g. /tmp: we
    # don't want to remove patches there to avoid surprises
    if args.output_directory != "":
        if commit_result:
            fatal("output directory can't be combined with -c or -m option")

        output = args.output_directory
        if has_patches(output) and not args.force:
            fatal("'%s' is not default output directory and has patches in it.\n"
                  "Force with --force or pass an empty/non-existent directory" % output)
    else:
        output = patchesdir

    genpatches(output, base, result)

    if commit_result:
        git("-C %s add series config *.patch" % output)
        commit_cmd = ["-C", output,  "commit"]
        if args.message:
            commit_cmd += ["-m", args.message]

        print(args.message)
        if git(commit_cmd, check=False, capture=False, stdout=None, stderr=None).returncode != 0:
            fatal("patches generated at '%s', but git-commit failed. Leaving result in place." % output)

    return 0


class PileCover:
    def __init__(self, m, version, baseline, pile_commit):
        self.m = m
        self.version = version
        self.baseline = baseline
        self.pile_commit = pile_commit

    def parse(fname):
        if fname is None:
            oldf = sys.stdin.buffer
        else:
            oldf = open(fname, 'rb')

        # look-ahead on first line and fix up if needed
        l0 = oldf.readline()
        f = tempfile.NamedTemporaryFile("wb+")
        if l0.startswith(b'From '):
            f.write(l0)
        else:
            f.write(b'From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001n\n')
            f.write(l0)

        f.write(oldf.read())

        if oldf != sys.stdin.buffer:
            oldf.close()

        f.seek(0)

        m = email.message_from_binary_file(f)
        if not m:
            error("No patches in '%s'" % fname if fname else "stdin")
            return None

        body_list = m.get_payload(decode=True).decode().splitlines()
        for l in reversed(body_list):
            if not l:
                continue
            if l.startswith("git-pile "):
                version = l[9:]
                break

            # last non-empty line should be git-pile version, otherwise
            # this doesn't seem to be a patch generated by git-pile: refuse
            error("Patch doesn't look like a git-pile cover letter: failed to find version information")
            return None

        for idx, l in enumerate(body_list):
            if l == "---":
                break
        else:
            error("Patch doesn't look like a git patch: failed to find diff separator '---'")
            return None

        start = idx + 1
        baseline = None
        pile_commit = None

        for idx, l in enumerate(body_list[start:]):
            if l.startswith("diff") or l.startswith('range-diff'):
                break

            elems = l.split(": ")
            if len(elems) != 2:
                continue

            if elems[0] == "baseline":
                baseline = elems[1]
            elif elems[0] == "pile-commit":
                pile_commit = elems[1]
            else:
                warn("Unknown pile information on cover letter:", elems[0])

        if not baseline or not pile_commit:
            error("Failed to find pile information in cover letter (baseline=%s, pile_commit=%s)" % (baseline, pile_commit))
            return None

        return PileCover(m, version, baseline, pile_commit)

    def dump(self, f):
        from_str = self.m.get_unixfrom() or "0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001"
        f.write("From %s\n" % from_str)

        for k, v in zip(self.m.keys(), self.m.values()):
            if k.lower() == "subject":
                has_subject = True

            if k.lower() == "subject" or k.lower() == "from":
                vfinal = ""
                for v, vencoding in email.header.decode_header(v):
                    if isinstance(v, bytes):
                        try:
                            vfinal = vfinal + v.decode(*([vencoding] if vencoding else []))
                        except LookupError:
                            # cover generated by git-pile should always be utf-8. Try
                            # it if for any reason the charset above is not reported
                            # correctly
                            vfinal = vfinal + v.decode('utf-8')
                    else:
                            vfinal = vfinal + v
                v = vfinal
            print("%s: %s" % (k, v), file=f)

        f.write("\n")
        f.write(self.m.get_payload(decode=False))


def git_am_solve_diff_hunk_conflicts(args, patchesdir):
    status = git(f"-C {patchesdir} status --porcelain").stdout.splitlines()
    resolved = True
    any_unmerged = False

    # double check we are actually resolving unmerged, we could have failed due
    # to other reasons
    for l in status:
        if l[0] == 'U' or l[1] == 'U':
            any_unmerged = True
            break

    if not any_unmerged:
        return False

    # Now check if we should actually try to fix the conflict
    if args.fuzzy is None:
        if sys.stdin.isatty():
            fuzzy = prompt_yesno("git am failed. Auto-solve trivial conflicts?", default=True)
        else:
            fuzzy = False
    else:
        fuzzy = args.fuzzy

    if not fuzzy:
        return False

    warn("\n\n--------------------------- git-pile")
    warn("git am failed, trying to fix conflicts automatically")

    sed = run_wrapper('sed', capture=True)

    # solve UU conflicts only, we don't really know how to resolve the others
    for f in status:
        if f[0] != 'U' and f[1] != 'U':
            continue
        if (f[0] == 'U') ^ (f[1] == 'U'):
            resolved = False
            continue

        f = f.split()[1]
        path = op.join(patchesdir, f)

        print(f"Trying to fix conflicts in {f}... ", end="", file=sys.stderr)
        sed(['-i', '-e', '/^<<<<<<< HEAD/ {N;N;N;N; s/<<<<<<< HEAD.*\\n@@.*\\n=======.*\\n\\(@@.*\\)\\n>>>>>>>.*/\\1/g}', path])

        # Check with all markers are gone
        any_markers = False
        with open(path) as fp:
            for l in fp:
                if l.startswith("<<<<<<< HEAD"):
                    any_markers = True
                    break

        if any_markers:
            resolved = False
            print("fail: couldn't solve all conflicts, some of them left behind", file=sys.stderr)
        else:
            print("done", file=sys.stderr)
            git(f"-C {patchesdir} add {f}")

    return resolved


def cmd_am(args):
    config = Config()
    if not config.check_is_valid():
        return 1

    root = git_root()
    patchesdir = op.join(root, config.dir)

    cover = PileCover.parse(args.mbox_cover)
    if not cover:
        return 1

    info("Entering '%s' directory" % config.dir)
    gitdir = git_worktree_get_git_dir()
    if op.isdir(op.join(gitdir, "rebase-apply")):
        fatal("Already on an am or rebase operation", file=sys.stderr)

    if args.strategy == "pile-commit":
        if git(["-C", patchesdir, "reset", "--hard", cover.pile_commit], check=False).returncode != 0:
            print("Could not checkout commit %s\n as baseline - you probably need to git-fetch it." % cover.pile_commit,
                  file=sys.stderr)

    with subprocess.Popen(["git", "-C", patchesdir, "am", "-3"],
            stdin=subprocess.PIPE, universal_newlines=True) as proc:
        cover.dump(proc.stdin)

    if proc.returncode != 0:
        if git_am_solve_diff_hunk_conflicts(args, patchesdir):
            info("Yay, fixed!")
            git(f"-C {patchesdir} am --continue")
            proc.returncode = 0

    if proc.returncode != 0:
        fatal("""git am failed, you will need to continue manually.

The '%s' directory is in branch '%s' in the middle of patching the series. You
need to fix the conflicts, add the files and finalize with:

    git am --continue

Good luck! ¯\_(ツ)_/¯"""  % (config.dir, config.pile_branch))

    if args.genbranch:
        info("Generating branch '%s'" % config.result_branch)
        genbranch_args = parse_args(["genbranch", "--force"])
        return cmd_genbranch(genbranch_args)

    return 0

def check_baseline_exists(baseline):
    ret = git_can_fail("cat-file -e {baseline}".format(baseline=baseline))
    if ret.returncode != 0:
        fatal("""baseline commit '%s' not found!

If the baseline tree has been force-pushed, the old baseline commits
might have been pruned from the local repository. If the baselines are
stored in the remote, they can be downloaded again with git fetch by
specifying the relevant refspec, either one-off directly in the command
or permanently in the git configuration file of the local repo.""" % (baseline))


def git_ref_is_ancestor(ancestor, ref):
    return git_can_fail(f"merge-base --is-ancestor {ancestor} {ref}").returncode == 0


def check_baseline_is_ancestor(baseline, ref):
    if not git_ref_is_ancestor(baseline, ref):
        fatal("""baseline '%s' is not an ancestor of ref '%s'.

Note that the pile baseline is implicitly used when no baseline is specified,
so this error commonly occurs when the pile is not updated when the working
branch is and no baseline is specified. If a branch non based on the pile
baseline is intentionally being used, a baseline must be specified as well.
See the help of this command for extra details""" % (baseline, ref))


# Parse refs from command line
#    branch  (branch@{u} is implicitly used)
#    ref1...ref2
#    ref1..ref2 ref3..ref4
def _parse_format_refs(refs, current_baseline):
    oldbaseline = None
    newbaseline = None
    oldref = None
    newref = None

    if len(refs) == 1:
        r = refs[0].split("...")
        if len(r) == 2:
            refs = r

    if len(refs) == 1:
        # Single branch name or "HEAD": the branch needs the upstream to be set in order to work
        branch = refs[0]

        if git_branch_exists(branch):
            newref = branch
        else:
            newref = git(f"symbolic-ref --short -q {branch}", check=False).stdout.strip()
            if not newref:
                fatal(f"'{branch}' does not name a branch")

        # use upstream of this branch as the old ref
        oldref = git(f"rev-parse --abbrev-ref {branch}@{{u}}", stderr=nul_f, check=False).stdout.strip()
        if not oldref:
            fatal(f"'{branch}' does not have an upstream. Either set with 'git branch --set-upstream-to'\nor pass old and new branches explicitly (e.g repo/internal...my-new-branch))")
    elif len(refs) == 2:
        r1 = refs[0].split("..")
        r2 = refs[1].split("..")
        if len(r1) == len(r2) and len(r1) == 2:
            try:
                oldbaseline = git(f"rev-parse {r1[0]}", stderr=nul_f).stdout.strip()
                newbaseline = git(f"rev-parse {r2[0]}", stderr=nul_f).stdout.strip()
                oldref = git(f"rev-parse {r1[1]}", stderr=nul_f).stdout.strip()
                newref = git(f"rev-parse {r2[1]}", stderr=nul_f).stdout.strip()
            except subprocess.CalledProcessError:
                if not oldbaseline or not newbaseline:
                    fatal(f"{r1} does not point to a valid range")
                fatal(f"{r2} does not point to a valid range")
        else:
            try:
                oldref = git(f"rev-parse {refs[0]}", stderr=nul_f).stdout.strip()
                newref = git(f"rev-parse {refs[1]}", stderr=nul_f).stdout.strip()
            except subprocess.CalledProcessError:
                if not oldref:
                    fatal(f"{refs[0]} does not point to a valid ref")
                fatal(f"{refs[1]} does not point to a valid ref")
    else:
        fatal("could not parse refs:", *refs)

    # there were no changes in the baseline, re-use current one
    if not oldbaseline:
        oldbaseline = current_baseline
        newbaseline = current_baseline

    return oldbaseline, newbaseline, oldref, newref



# @range_diff_commits is a string with multiple lines containing
# the stat lines of the git-range-diff output. They have the following form:
#
#     1:  34cf518f0aab ! 1:  3a4e12046539 <commit message>
#
# Those lines are parsed to detect what were the commits changed, added
# or removed
#
# Output is given in lists of tuples for changed, added and removed commits:
#
#     (old_commit_sha, new_commit_sha, new_position_in_branch)
#
# The last item in the return is a list of files that can be used as a "diff filter"
# so to ignore commits that had only their sha changed, but remain the same before
# in the range comparison
def _parse_range_diff(range_diff_commits):
    c_commits = []
    a_commits = []
    d_commits = []

    # we maintain the position of each commit in the new branch so we can sort
    # them later
    n = 1

    for c in range_diff_commits:
        if not c:
            continue

        _, old_sha1, s, _, new_sha1, _ = c.split(maxsplit=5)
        if s == "!":
            c_commits += [(old_sha1, new_sha1, n)]
        elif s == ">":
            a_commits += [(old_sha1, new_sha1, n)]
        elif s == "<":
            d_commits += [(old_sha1, new_sha1, n)]

        n += 1

    diff_filter_list = ["config", "series"]
    diff_filter_list += [generate_series_list(x[0], "*.patch") for x in c_commits]
    diff_filter_list += [generate_series_list(x[1], "*.patch") for x in c_commits]
    diff_filter_list += [generate_series_list(x[1], "*.patch") for x in a_commits]
    diff_filter_list += [generate_series_list(x[0], "*.patch") for x in d_commits]
    diff_filter_list = list(orderedset(diff_filter_list))
    a_commits.sort(key=lambda x: x[2])

    return c_commits, a_commits, d_commits, diff_filter_list


def assert_format_patch_compatible_args(args):
    if args.commit_with_message and args.file:
        fatal("-C and -F options are mutually exclusive")


def cmd_format_patch(args):
    assert_required_tools()
    assert_format_patch_compatible_args(args)

    config = Config()
    if not config.check_is_valid():
        return 1

    root = git_root()
    patchesdir = op.join(root, config.dir)

    oldbaseline, newbaseline, oldref, newref = _parse_format_refs(args.refs, get_baseline(patchesdir))
    # make sure the specified baseline commits are part of the branches
    check_baseline_is_ancestor(oldbaseline, oldref)
    check_baseline_is_ancestor(newbaseline, newref)

    if not args.allow_local_pile_commits and not git_ref_is_ancestor(f"{config.pile_branch}", f"{config.pile_branch}@{{u}}"):
        fatal(f"""'{config.pile_branch}' branch contains local commits that aren't visible outside this repo.

If this is indeed the desired behavior, pass --allow-local-pile-commits or --local as
option to this command.""")

    # possibly too big diff, just avoid it for now - force it to false
    if oldbaseline != newbaseline:
        args.no_full_patch = True

    creation_factor = f"--creation-factor={args.creation_factor}" if args.creation_factor else ""
    range_diff_commits = git("range-diff --no-color --no-patch {creation_factor} {oldbaseline}..{oldref} {newbaseline}..{newref}".format(
            creation_factor=creation_factor, oldbaseline=oldbaseline, newbaseline=newbaseline, oldref=oldref, newref=newref)).stdout.split("\n")

    c_commits, a_commits, d_commits, diff_filter_list = _parse_range_diff(range_diff_commits)

    # get a simple diff of all the changes to attach to the coverletter filtered by the
    # output of git-range-diff
    with temporary_worktree(config.pile_branch, root) as tmpdir:
        ret = genpatches(tmpdir, newbaseline, newref)
        if ret != 0:
            return 1

        git("-C %s add --force -A" % tmpdir)
        with tempfile.NamedTemporaryFile('w+') as order_file:
            for l in diff_filter_list:
                order_file.write(l + "\n")
            order_file.flush()

            diff = git(["-C", tmpdir, "diff", "--cached", "-p", "--stat", '-O', order_file.name, "--no-ext-diff", "--",
                        *diff_filter_list]).stdout
            if not diff:
                fatal("Nothing changed from %s..%s to %s..%s"
                        % (oldbaseline, config.result_branch, newbaseline, newref))

    if not args.output_directory and config.format_output_directory:
        output = config.format_output_directory
    else:
        output = args.output_directory

    os.makedirs(output or '.', exist_ok=True)
    rm_patches(output or '.')

    total_patches = len(a_commits)
    if not args.no_full_patch:
        total_patches += 1

    cover_fn = "0000-cover-letter.patch"
    full_tree_patch_fn = f"{total_patches:04d}-full-tree-diff.patch"

    if args.subject_prefix:
        prefix = args.subject_prefix
    else:
        try:
            prefix = git("config --get format.subjectprefix").stdout.strip()
        except subprocess.CalledProcessError:
            prefix = "PATCH"

    if args.reroll_count:
        reroll_count_str = f"v{args.reroll_count}"
        prefix = f"{prefix} {reroll_count_str}"
        cover_fn = f"{reroll_count_str}-{cover_fn}"
        full_tree_patch_fn = f"{reroll_count_str}-{full_tree_patch_fn}"
    else:
        reroll_count_str = ""

    zero_fill = int(log10_or_zero(total_patches)) + 1

    cover_subject, cover_body = get_cover_letter_message(args.commit_with_message, args.file, args.signoff)
    gen_cover_letter(diff, op.join(output, cover_fn), total_patches, newbaseline,
                     git("rev-parse {ref}".format(ref=config.pile_branch)).stdout.strip(),
                     prefix, range_diff_commits, config.format_add_header,
                     cover_subject, cover_body)
    print(op.join(output, cover_fn))

    with tempfile.TemporaryDirectory() as d:
        for i, c in enumerate(a_commits):
            format_cmd = ["format-patch", "--subject-prefix=PATCH", "--zero-commit", "--signature="]
            if config.format_add_header:
                format_cmd.extend(["--add-header", config.format_add_header])
            format_cmd.extend(["-o", d, "-N", "-1", c[1]])

            old = git(format_cmd).stdout.strip()
            new = op.join(output, "%s%04d-%s" % (f"{reroll_count_str}-" if reroll_count_str else "",
                                                 i + 1,
                                                 old[len(d) + 1 + 5:]))

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
                                   prefix=prefix, i=str(i + 1).zfill(zero_fill),
                                   n_patches=total_patches,
                                   title=title))
                        break
                    else:
                        fatal("patch '%s' missing subject?" % old)

                    # write all the other lines after Subject header at once
                    newf.writelines(oldf.readlines())

            print(new)

        if not args.no_full_patch:
            gen_full_tree_patch(op.join(output, full_tree_patch_fn), total_patches,
                                oldbaseline, newbaseline, oldref, newref,
                                prefix, config.format_add_header)
            print(op.join(output, full_tree_patch_fn))

    return 0


def _genbranch(root, patchesdir, config, args):
    if not config.check_is_valid():
        return 1

    baseline = get_baseline(patchesdir)

    # Make sure the baseline hasn't been pruned
    check_baseline_exists(baseline);

    try:
        patchlist = [op.join(patchesdir, p.strip())
                for p in open(op.join(patchesdir, "series")).readlines()
                if len(p.strip()) > 0 and p[0] != "#"]
    except FileNotFoundError:
        patchlist = []

    stdout = nul_f if args.quiet else sys.stdout
    stderr = sys.stderr

    if not args.dirty:
        apply_cmd = ["-c", "core.splitIndex=true", "am", "--no-3way"]
        if config.genbranch_committer_date_is_author_date:
            apply_cmd.append("--committer-date-is-author-date")
        if args.fix_whitespace:
            apply_cmd.append("--whitespace=fix")

        env = os.environ.copy()
        if config.genbranch_user_name:
            env['GIT_COMMITTER_NAME'] = config.genbranch_user_name
        if config.genbranch_user_email:
            env['GIT_COMMITTER_EMAIL'] = config.genbranch_user_email
    else:
        env = None
        apply_cmd = ["apply", "--unsafe-paths", "-p1"]

    # "In-place mode" resets and applies patches directly to working
    # directory.  If conflicts arise, user can resolve them and continue
    # application via 'git am --continue'.
    if args.inplace:
        if patchesdir == os.getcwd():
            fatal("Wrong directory: can't git-reset over pile branch checkout")
        gitdir = git_worktree_get_git_dir()
        if os.path.exists(op.join(gitdir, "rebase-apply")):
            fatal("'git am' already in progress on working tree.")
        if os.path.exists(op.join(gitdir, "rebase-merge")):
            fatal("'git rebase' already in progress on working tree.")

        if not args.branch:
            # use whatever is currently checked out, might as well be in
            # detached state
            git("reset --hard %s" % baseline)
        else:
            git("checkout -B %s %s" % (args.branch, baseline))

        if patchlist:
            with git_split_index():
                ret = git_can_fail(apply_cmd + patchlist, stdout=stdout, stderr=stderr, env=env, start_new_session=True)

            if ret.returncode != 0:
                fatal("""Conflict encountered while applying pile patches.

Please resolve the conflict, then run "git am --continue" to continue applying
pile patches.""")

        return 0

    # work in a separate directory to avoid cluttering whatever the user is doing
    # on the main one
    with temporary_worktree(baseline, root) as d:
        branch = args.branch if args.branch else config.result_branch
        path = git_worktree_get_checkout_path(root, branch)

        if path and not args.force:
            error("can't use branch '%s' because it is checked out at '%s'" % (branch, path))
            return 1

        if patchlist:
            git(["-C", d] + apply_cmd + patchlist, stdout=stdout, stderr=stderr)

        if args.dirty:
            raise temporary_worktree.Break

        head = git(["-C", d, "rev-parse", "HEAD"]).stdout.strip()

        if path:
            # args.force checked earlier
            git("-C %s reset --hard %s" % (path, head), stdout=nul_f, stderr=nul_f)
        else:
            git("-C %s checkout -f -B %s %s" % (d, branch, head), stdout=nul_f, stderr=nul_f)

    return 0


def cmd_genbranch(args):
    config = Config()
    root = git_root()
    patchesdir = op.join(root, config.dir)

    return _genbranch(root, patchesdir, config, args)

# returns (top_linear_ref, refspec)
# - top_linear_ref is the the latest ref from the linearized branch if we have one
# - refspec is something suitable to pass to rev-list/log to get the missing
#   refs from pile branch
def get_refs_from_linearized(incremental, pile_branch, linear_branch, notes_ref):
    if not incremental:
        return None, pile_branch

    if not git_ref_exists(f"refs/notes/{linear_branch}"):
        return None, pile_branch

    proc = git_can_fail(f'rev-list --no-merges {linear_branch}', stderr=nul_f)
    if proc.returncode or not proc.stdout:
        return None, pile_branch

    refs = proc.stdout.strip().split('\n')
    key = "pile-commit: "
    for ref in refs:
        notes = git(f"log --notes={notes_ref} --format=%N -1 {ref}").stdout.strip().split("\n")
        for n in notes:
            if n.startswith(key):
                return refs[0], f"{n[len(key):]}..{pile_branch}"

    return None, pile_branch


def cmd_genlinear_branch(args):
    config = Config()
    if not config.check_is_valid():
        return 1

    root = git_root()
    branch = config.linear_branch or args.branch
    if not branch:
        fatal("Branch not specified in command-line and not configured: use -b argument or configure in pile.linear-branch")

    notes_ref = branch

    parent_ref, pile_range = get_refs_from_linearized(args.incremental, config.pile_branch, branch, notes_ref)
    refs = git(f'rev-list --no-merges --reverse {pile_range}').stdout.strip().splitlines()
    if not refs:
        info("Nothing to do.")
        return 0

    with temporary_worktree(refs[0], root) as piledir:
        # we have to checkout something in the directory we are going to
        # genbranch in order to please git-worktree. However this is just a
        # place to dump intermediate state that we are continuously resetting.
        # BASELINE from the first rev is a good guesstimate, but it may not
        # exist. In that case, just checkout anything, we are going to reset
        # to a new commit as the first thing anyway
        commit = get_baseline(piledir) or refs[0]
        with temporary_worktree(commit, root) as resultdir:
            last_good_ref = None
            tree = "tree " + git(f"log --format=%T -1 {parent_ref}").stdout.strip() if parent_ref else None

            # avoid exit() from genbranch - we want to recover and continue
            set_fatal_behavior("raise")
            genbranch_args = parse_args(["genbranch", "-i", "-q"])

            total_refs = len(refs)

            for idx, rev in enumerate(refs):
                git(f'-C {piledir} reset --hard {rev}')
                info(f'Generating branch for {rev} ({idx + 1}/{total_refs}) ', end='')
                sys.stdout.flush()
                ts0 = timeit.default_timer()

                try:
                    with redirect_stdout(nul_f), redirect_stderr(nul_f), pushdir(resultdir, root):
                        _genbranch(root, piledir, config, genbranch_args)

                        tree = next((x for x in git("cat-file commit HEAD").stdout.strip().splitlines() if x.startswith("tree")), None)
                        last_good_ref = rev
                except KeyboardInterrupt:
                    raise
                except:
                    # try to cleanup to recover checkout
                    git_can_fail(f"-C {resultdir} am --abort", stderr=nul_f, stdout=nul_f)
                    git_can_fail(f"-C {resultdir} cleant  -fxd", stderr=nul_f, stdout=nul_f)

                    print(f"[ {timeit.default_timer() - ts0:.2f}s ]")

                    if not parent_ref:
                        # EMPTY_TREE_HASH = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
                        # git("hash-object -t tree -w --stdin", stdin=nul_f).stdout.strip()
                        tree = "tree 4b825dc642cb6eb9a060e54bf8d69288fbee4904"
                    else:
                        error(f"could not genbranch from {rev}.\nPrevious rev will be used and empty commit generated")
                else:
                    print(f"[ {timeit.default_timer() - ts0:.2f}s ]")

                # Input to create new commit:
                # tree comes from the result of genbranch
                # parent comes from the previous result of genbranch, cached in parent_ref
                # author, committer and commit message comes from the pile commit
                if not tree:
                    fatal(f"Unknown tree hash for commit {rev}")

                commit_input = [tree]
                if parent_ref:
                    commit_input += [f"parent {parent_ref}"]

                out = git(f"cat-file commit {rev}").stdout.strip().split('\n')
                for idx, l in enumerate(out):
                    if not l:
                        break
                    if l.startswith("tree") or l.startswith("parent"):
                        continue
                    commit_input += [l]
                commit_input += out[idx:]

                proc = subprocess.Popen(["git", "hash-object", "-t", "commit", "-w", "--stdin" ],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
                out, _ = proc.communicate("\n".join(commit_input))
                if proc.returncode or not out:
                    fatal(f"Couldn't create commit object for {rev} - {commit_input}")

                parent_ref = out.strip()

                # update notes
                notes = f"pile-commit: {rev}"
                if rev != last_good_ref and last_good_ref:
                    notes += f"\npile-commit-reused: {last_good_ref}"
                git(["notes", f"--ref={notes_ref}", "add", "-f", "-m", notes, parent_ref])

                if parent_ref:
                    git(f"update-ref refs/heads/{branch} {parent_ref}")

    print("Done.")

    return 0


def cmd_baseline(args):
    config = Config()
    if not config.check_is_valid():
        return 1

    root = git_root()
    patchesdir = op.join(root, config.dir)
    b_dir = get_baseline(patchesdir)
    b_branch = get_baseline_from_branch(config.pile_branch)

    if b_dir != b_branch:
        fatal("Pile branch '%s' has baseline %s, but directory is currently at %s"
              % (config.pile_branch, b_branch, b_dir))

    print(b_branch)

    return 0


def cmd_destroy(args):
    # everything here should work even if we have an invalid/partial
    # configuration.
    config = Config()

    # everything here is relative to root
    os.chdir(git_root())

    # implode - we have the cached values saved in config
    if git("config --remove-section pile", check=False, stderr=nul_f).returncode != 0:
        fatal("pile not initialized")

    git_ = run_wrapper('git', capture=True, check=False, print_error_as_ignored=True)
    rm_ = run_wrapper('rm', capture=True, check=False, print_error_as_ignored=True)

    if config.dir and op.exists(config.dir):
        git_("worktree remove --force {d}".format(d=config.dir))
        rm_("-rf {d}".format(d=config.dir))

    git_("worktree prune")

    if config.pile_branch:
        git_("branch -D {d}".format(d=config.pile_branch))


def cmd_reset(args):
    config = Config()
    if not config.check_is_valid():
        return 1

    # everything here is relative to root
    gitroot = git_root()

    # ensure we have it checked-out
    pile_dir = git_worktree_get_checkout_path(gitroot, config.pile_branch)
    if not pile_dir:
        fatal("Could not find checkout of %s branch, refusing to reset.\nYou should probably inspect '%s')"
              % (config.pile_branch, config.dir))

    remote_pile = git_can_fail("rev-parse --abbrev-ref %s@{u}" % config.pile_branch).stdout.strip()
    if not remote_pile:
        fatal("Branch %s doesn't have an upstream" % config.pile_branch)

    if args.inplace:
        branch_dir = os.getcwd()
        if branch_dir == pile_dir:
            fatal("In-place reset can't reset both %s and %s branches to the same commit\n"
                  "You are probably in the wrong directory for in-place reset."
                  % (config.pile_branch, config.result_branch))

        local_branch = git("rev-parse --abbrev-ref HEAD").stdout.strip()
        if local_branch == "HEAD":
            local_branch = git("rev-parse --short HEAD").stdout.strip() + " (detached)"
    else:
        branch_dir = git_worktree_get_checkout_path(gitroot, config.result_branch)
        if not branch_dir:
            fatal("Could not find checkout of %s branch, refusing to reset.\nYou should probably inspect '%s'"
                  % (config.result_branch, gitroot))
        local_branch = config.result_branch

    remote_branch = git_can_fail("rev-parse --abbrev-ref %s@{u}" % config.result_branch).stdout.strip()
    if not remote_branch:
        fatal("Branch %s doesn't have an upstream" % config.result_branch)

    git(["-C", pile_dir, "reset", "--hard", remote_pile])
    print("{local_branch:<20}-> {remote_branch:<20} {dir}".format(
          local_branch=config.pile_branch, remote_branch=remote_pile, dir=pile_dir))

    git(["-C", branch_dir, "reset", "--hard", remote_branch])
    print("{local_branch:<20}-> {remote_branch:<20} {dir}".format(
          local_branch=local_branch, remote_branch=remote_branch, dir=branch_dir))

    print("Branches synchronized with their current remotes")


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
    parser_init = subparsers.add_parser('init', help="Initialize configuration of an empty pile in this repository")
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
        help="Branch to be created when applying patches from PILE_BRANCH on top of BASELINE (default: %(default)s)",
        metavar="RESULT_BRANCH",
        default="internal")
    parser_init.set_defaults(func=cmd_init)

    # setup
    parser_setup = subparsers.add_parser('setup', help="Setup/copy configuration from a remote or already created branches")
    parser_setup.add_argument(
        "-d", "--dir",
        help="Directory in which to place patches - same argument as for git-pile init (default: %(default)s)",
        metavar="DIR",
        default="patches")
    parser_setup.add_argument(
        "-f", "--force",
        help="Always create RESULT_BRANCH, even if it's checked out in any path",
        action="store_true",
        default=False)
    parser_setup.add_argument("pile_branch",
        help="Remote or local branch used to store the physical patch files. "
             "In case a remote branch is passed, a local one will be created "
             "with the same name as in remote and its upstream configuration "
             "will be set accordingly (as in 'git branch <local-name> --set-upstream-to=<pile-branch>'. "
             "Examples: 'origin/pile', 'myfork/pile', 'internal-remote/internal-branch'. "
             "An existent local branch may be used as long as it looks like a "
             "pile branch. Examples: 'pile', 'patches', etc.", metavar="PILE_BRANCH")
    parser_setup.add_argument("result_branch",
        help="Remote or local branch that will be generated as a result of applying "
             "the patches from PILE_BRANCH to the base commit (baseline). In "
             "case a remote branch is passed, a local one will be created "
             "with the same name as in remote and its upstream configuration "
             "will be set accordingly (as in 'git branch <local-name> --set-upstream-to=<pile-branch>. "
             "Examples: 'origin/internal', 'myfork/wip', 'rt/linux-4.18.y-rt-rebase'. "
             "An existent local branch may be used as long as it looks like a "
             "result branch, i.e. it must contain the baseline commit configured in PILE_BRANCH. "
             "If this argument is omitted, the current checked out branch is used in the same way local "
             "branches are handled.", metavar="RESULT_BRANCH", nargs="?")
    parser_setup.set_defaults(func=cmd_setup)

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
        "-c", "--commit-result",
        help="Commit the generated patches to the pile on success. This is only "
             "valid without a -o option",
        action="store_true",
        default=False)
    parser_genpatches.add_argument(
        "-m", "--message",
        help="Use the given MSG as the commit message. This implies the "
             "--commit-result option",
        metavar="MSG")
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
        "-f", "--force",
        help="Always create RESULT_BRANCH, even if it's checked out in any path",
        action="store_true",
        default=False)
    parser_genbranch.add_argument(
        "-q", "--quiet",
        help="Quiet mode - do not print list of patches",
        action="store_true",
        default=False)
    parser_genbranch.add_argument(
        "-i", "--inplace", "--in-place",
        help="Generate branch in-place, enable conflict resolution and recovery: the current branch in the CWD is reset to the baseline commit and patches applied",
        action="store_true",
        dest="inplace",
        default=False)
    parser_genbranch.add_argument(
        "--fix-whitespace",
        help="Pass --whitespace=fix to git am to fix whitespace",
        action="store_true")
    parser_genbranch.set_defaults(func=cmd_genbranch)
    parser_genbranch.add_argument(
        "--dirty",
        help="Just apply the patches, do not create the corresponding commits",
        action="store_true",
        dest="dirty",
        default=False)

    # format-patch
    parser_format_patch = subparsers.add_parser('format-patch', help="Generate patches from BASELINE..HEAD and save patch series to output directory to be shared on a mailing list",
        formatter_class=argparse.RawTextHelpFormatter)
    parser_format_patch.add_argument(
        "-o", "--output-directory",
        help="Use OUTPUT_DIR to store the resulting files instead of the format-output-directory from config (default: CWD)",
        metavar="OUTPUT_DIR",
        default="")
    parser_format_patch.add_argument(
        "-f", "--force",
        help="Force use of OUTPUT_DIR even if it has patches. The existent patches will be\n"
             "removed.",
        action="store_true",
        default=False)
    parser_format_patch.add_argument(
        "--subject-prefix",
        help="Instead of the standard [PATCH] prefix in the subject line, use\n"
             "[<Subject-Prefix>]. See git-format-patch(1) for details.",
        metavar="SUBJECT_PREFIX",
        default=None)
    parser_format_patch.add_argument(
        "--no-full-patch",
        help="Do not generate patch with full diff\n",
        action="store_true",
        default=False)
    parser_format_patch.add_argument(
        "--allow-local-pile-commits", "--local",
        help="Bypass check for local pile commits to allow partial patch series. By default "
             "git-pile checks the pile branch is in sync with the remote to avoid a situation "
             "where the patch series can't be applied by another person due to missing dependencies. "
             "That is a common scenario when preparing a v2 of a patch series and having the v1 "
             "temporarily applied.  However you may to avoid this check if this is what you really "
             "intend, preparing another patch series on top. In this case beware you will need to use "
             "the additional REFS parameter, pointing git-pile to both the old and new states of RESULT_BRANCH",
        action="store_true",
        default=False)
    parser_format_patch.add_argument(
        '--creation-factor',
        help="--creation-factor argument passed to git-range-diff. It controls the percentage of change used to consider a patch new vs modified. See GIT-RANGE-DIFF(1)",
        action="store",
        default=None)
    parser_format_patch.add_argument(
        "-C", "--reuse-message",
        help="Take an existing commit object, and reuse the log message as the cover-letter, like documented in GIT-COMMIT(1)",
        dest="commit_with_message",
        metavar="COMMIT")
    parser_format_patch.add_argument(
        '-F', '--file',
        help="Take the commit message from the given file. Use - to read the message from the standard input. Like documented in GIT-COMMIT(1)",
        metavar="FILE")
    parser_format_patch.add_argument(
        '--signoff',
        help="Add s-o-b to the cover letter, like git-merge --signoff or git-commit --signoff do",
        action="store_true",
        default=False)
    parser_format_patch.add_argument(
        '--reroll-count', '-v',
        help="Mark the series as the <n>-th iteration of the topic. This mimics the same behavior from git-format-patch",
        action="store")
    parser_format_patch.add_argument(
        "refs",
        help="""
Same arguments as the ones received by range-diff in its several forms plus a
shortcut. From more verbose to the easiest ones:
1) OLD_BASELINE..OLD_RESULT_HEAD NEW_BASELINE..NEW_RESULT_HEAD
    This should be used when rebasing the RESULT_BRANCH and thus having
    different baselines

2) OLD_RESULT_HEAD...NEW_RESULT_HEAD or OLD_RESULT_HEAD NEW_RESULT_HEAD
    This assumes the baseline remained the same. In the first form, the
    same as used by git-range-diff, note the triple dots rather than double.

3) OLD_RESULT_HEAD NEW_RESULT_HEAD
    Same as (2)

3) HEAD or no arguments
    This is a shortcut: the current branch will be used as NEW_RESULT_HEAD and
    the upstream of this branch as OLD_RESULT_HEAD. Example: if RESULT_BRANCH
    is internal, this is equivalent to: internal@{u}...internal""",
        metavar="REFS",
        nargs="*",
        default=["HEAD"])
    parser_format_patch.set_defaults(func=cmd_format_patch)

    # am
    parser_am = subparsers.add_parser('am', help="Apply patch, generated by git-pile format-patch, to the series and recreate RESULT_BRANCH")
    parser_am.add_argument(
        "-g", "--genbranch",
        help="When patch is correctly applied, also force-generate the "
        "RESULT_BRANCH - this is the equivalent of calling "
        "\"git pile genbranch -f\" after the command returns.",
        action="store_true",
        default=False)
    parser_am.add_argument(
        "mbox_cover",
        help="Mbox/patch file containing the coverletter generated by git-pile. "
        "If more than one patch is contained in the mbox, the first one is "
        "assumed to be the cover. "
        "If no arguments are passed, the mbox is read from stdin",
        nargs="?")
    parser_am.add_argument(
        "-s", "--strategy",
        help="Select the strategy used to apply the patch. \"top\", the default, "
             "tries to apply the patch on top of PILE_BRANCH. \"pile-commit\" "
             "first reset the pile branch to the commit saved in the cover "
             "letter before proceeding - this allows to replicate the "
             "exact same tree as the one that generated the cover. However "
             "the PILE_BRANCH will have diverged.",
        choices=["top", "pile-commit"],
        default="top")

    parser_am.add_argument(
        "--no-fuzzy",
        action="store_false",
        dest="fuzzy",
        default=None)
    parser_am.add_argument(
        "--fuzzy",
        help="Allow to apply a patch even with conflicts in the diff hunk line numbers. "
             "When using this option we will automatically solving the conflicts of this kind "
             "by taking `theirs` version as the correct. See 'HOW CONFLICTS ARE PRESENTED' in "
             "GIT-MERGE(1) [Default: prompt if running on terminal, otherwise no]",
        action="store_true",
        dest="fuzzy",
        default=None)
    parser_am.set_defaults(func=cmd_am)

    # genlinear-branch
    parser_genlinear_branch = subparsers.add_parser('genlinear-branch', help="Generate linear branch from genbranch on each pile revision")
    parser_genlinear_branch.add_argument(
        "-b", "--branch",
        help="Use BRANCH to store the linear result branch [Default: pile.linear-branch from config]",
        metavar="BRANCH",
        default="")
    parser_genlinear_branch.add_argument(
        "-r", "--recreate", "--no-incremental",
        help="Do not reuse branch to skip revisions that were already previously "
             "executed through genlinear-branch. Instead, work in non-incremental "
             "mode, recreating the branch from scratch",
        action="store_false",
        dest="incremental",
        default=True)
    parser_genlinear_branch.set_defaults(func=cmd_genlinear_branch)

    # baseline
    parser_baseline = subparsers.add_parser('baseline', help="Return the baseline commit hash")
    parser_baseline.set_defaults(func=cmd_baseline)

    # destroy
    parser_destroy = subparsers.add_parser('destroy', help="Destroy all git-pile on this repo")
    parser_destroy.set_defaults(func=cmd_destroy)

    # reset
    parser_reset = subparsers.add_parser('reset', help="Reset RESULT_BRANCH and PILE_BRANCH to match remote")
    parser_reset.add_argument(
        "-i", "--inplace", "--in-place",
        help="Reset branch in-place: the current branch in the CWD is reset to the upstream of RESULT_BRANCH",
        action="store_true",
        dest="inplace",
        default=False)
    parser_reset.set_defaults(func=cmd_reset)

    # add options to all subparsers
    for _, subp in subparsers.choices.items():
        subp.add_argument(
            "--debug",
            help="Turn on debugging output",
            action="store_true", default=False)

    parser.add_argument('-v', '--version', action='version', version='git-pile ' + __version__)

    try:
        argcomplete.autocomplete(parser)
    except NameError:
        pass

    args = parser.parse_args(cmd_args)
    if not hasattr(args, "func"):
        parser.print_help()
        return None

    if args.debug:
        set_debugging(True)

    return args


def main(*cmd_args):
    args = parse_args(cmd_args)
    if not args:
        return 1

    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130

    return 1
