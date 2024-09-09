# SPDX-License-Identifier: LGPL-2.1+
"""
Module that implements the genbranch operation.
"""
import argparse
import contextlib
import os
import os.path as op
import pathlib
import subprocess
import sys

from .config import Config
from .cli import PileCommand
from .genbranch_caching import GenbranchCache
from .gitutil import (
    git_split_index,
    git_temporary_worktree,
    git_worktree_get_checkout_path,
    git_worktree_get_git_dir,
)
from .helpers import (
    error,
    fatal,
    git,
    git_can_fail,
    nul_f,
    prompt_yesno,
    run_wrapper,
    warn,
)
from .pile import Pile


def genbranch(config, args):
    with contextlib.ExitStack() as exit_stack:
        return genbranch_with_exit_stack(config, args, exit_stack)


def genbranch_with_exit_stack(config, args, exit_stack):
    if args.no_config:
        if not (args.external_pile or args.pile_rev):
            fatal("--external-pile or --pile-rev is required when using --no-config")
        if not (args.inplace or args.branch):
            fatal("--inplace or --branch is required when using --no-config")
    elif not config.check_is_valid():
        return 1

    if args.external_pile and args.pile_rev:
        fatal("options --external-pile and --pile-rev are mutually exclusive")

    if args.external_pile:
        patchesdir = args.external_pile
    elif args.pile_rev:
        patchesdir = exit_stack.enter_context(git_temporary_worktree(args.pile_rev, config.root))
    else:
        patchesdir = op.join(config.root, config.dir)

    if args.use_cache is None:
        args.use_cache = config.genbranch_use_cache

    pile = Pile(path=patchesdir, baseline=args.baseline)

    # Make sure the baseline hasn't been pruned
    check_baseline_exists(pile.baseline())

    try:
        patchlist = [op.join(patchesdir, p.name) for p in pile.series()]
    except FileNotFoundError:
        patchlist = []

    stdout = nul_f if args.quiet else sys.stdout
    stderr = sys.stderr

    if not args.dirty:
        apply_cmd = ["-c", "core.splitIndex=true", "am", "--no-3way", "--whitespace=warn"]
        # Let's be conservative: any change in the default behavior of genbranch
        # must cause caching to be disabled.
        cache_not_allowed_reasons = []

        if config.genbranch_committer_date_is_author_date:
            apply_cmd.append("--committer-date-is-author-date")
        else:
            cache_not_allowed_reasons.append("config pile.genbranch-commiter-date-is-author-date is false")

        if args.fix_whitespace:
            apply_cmd.append("--whitespace=fix")
            cache_not_allowed_reasons.append("using option --fix-whitespace")

        env = os.environ.copy()
        if config.genbranch_user_name:
            env["GIT_COMMITTER_NAME"] = config.genbranch_user_name

        if config.genbranch_user_email:
            env["GIT_COMMITTER_EMAIL"] = config.genbranch_user_email

        cache_allowed = len(cache_not_allowed_reasons) == 0
        if args.use_cache and not cache_allowed:
            cache_not_allowed_reasons = "; ".join(cache_not_allowed_reasons)
            warn(f"Caching disabled because of non-default genbranch operation: {cache_not_allowed_reasons}")
    else:
        env = None
        apply_cmd = ["apply", "--unsafe-paths", "-p1"]

    if not args.dirty and args.use_cache and cache_allowed:
        if not config.genbranch_cache_path:
            fatal("Missing cache path (config value for pile.genbranch-cache-path is empty)")
        cache_path = op.join(git_worktree_get_git_dir(config.root, force_absolute=True), config.genbranch_cache_path)
        committer_ident = git(["var", "GIT_COMMITTER_IDENT"], env=env).stdout
        cache = GenbranchCache(cache_path, committer_ident=committer_ident)
        # Use Pile from a revision if possible, so we do not calculate sha1 for
        # each patch.
        pile_for_cache = pile
        cache_pile_rev = args.pile_rev

        if not cache_pile_rev:
            try:
                if git(["-C", patchesdir, "status", "--porcelain"], stderr=nul_f).stdout.strip() == "":
                    cache_pile_rev = git(["-C", patchesdir, "rev-parse", "HEAD"]).stdout.strip()
            except subprocess.CalledProcessError:
                pass

        if cache_pile_rev:
            pile_for_cache = Pile(rev=cache_pile_rev, rev_repo_path=patchesdir, baseline=args.baseline)

        effective_baseline, patchlist_offset = cache.search_best_base(pile_for_cache)
        if patchlist_offset:
            patchlist = patchlist[patchlist_offset:]
    else:
        effective_baseline = pile.baseline()
        cache = None

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
            git(f"reset --hard {effective_baseline}")
        else:
            git(f"checkout -B {args.branch} {effective_baseline}")

        any_fallback = False

        if patchlist:
            with git_split_index():
                ret = git_can_fail(apply_cmd + patchlist, stdout=stdout, stderr=stderr, env=env, start_new_session=True)
                while ret.returncode != 0:
                    if not git_am_apply_fallbacks(apply_cmd, args, stdout, stderr, env):
                        break

                    any_fallback = True

                    # check for progress, if am --continue fails without progressing a single patch
                    # then we bailout
                    next_patch = pathlib.Path(git_worktree_get_git_dir()) / "rebase-apply" / "next"
                    out0 = next_patch.read_text()
                    ret = git_can_fail("am --continue", stdout=stdout, stderr=stderr, env=env, start_new_session=True)
                    if ret.returncode != 0:
                        out1 = next_patch.read_text()
                        if out1 == out0:
                            break

            if ret.returncode != 0:
                fatal(
                    """Conflict encountered while applying pile patches.

Please resolve the conflict, then run "git am --continue" to continue applying
pile patches."""
                )

        if any_fallback:
            warn(
                "Branch created successfully, but with the use of fallbacks\n"
                "The result branch doesn't correspond to the current state\n"
                "of the pile. Pile needs to be updated to match result branch"
            )

        if cache and not any_fallback:
            cache.update(pile_for_cache, "HEAD")
            cache.save()

        return 0

    # work in a separate directory to avoid cluttering whatever the user is doing
    # on the main one
    with git_temporary_worktree(effective_baseline, config.root) as d:
        branch = args.branch if args.branch else config.result_branch
        path = git_worktree_get_checkout_path(config.root, branch)

        if path and not args.force:
            error(f"can't use branch '{branch}' because it is checked out at '{path}'")
            return 1

        if patchlist:
            git(["-C", d] + apply_cmd + patchlist, stdout=stdout, stderr=stderr, env=env)

        if args.dirty:
            raise git_temporary_worktree.Break

        head = git(["-C", d, "rev-parse", "HEAD"]).stdout.strip()

        if cache:
            cache.update(pile_for_cache, head)
            cache.save()

        if path:
            # args.force checked earlier
            git(f"-C {path} reset --hard {head}", stdout=nul_f, stderr=nul_f)
        else:
            git(f"-C {d} checkout -f -B {branch} {head}", stdout=nul_f, stderr=nul_f)

    return 0


def check_baseline_exists(baseline):
    ret = git_can_fail("cat-file -e {baseline}".format(baseline=baseline))
    if ret.returncode != 0:
        fatal(
            f"""baseline commit '{baseline}' not found!

If the baseline tree has been force-pushed, the old baseline commits
might have been pruned from the local repository. If the baselines are
stored in the remote, they can be downloaded again with git fetch by
specifying the relevant refspec, either one-off directly in the command
or permanently in the git configuration file of the local repo."""
        )


def git_am_apply_fallbacks(apply_cmd, args, stdout, stderr, env):
    # we can only use fallbacks when applying patches with git-am
    if "am" not in apply_cmd:
        return False

    if not should_try_fuzzy(args, "genbranch failed. Auto-solve trivial conflicts?"):
        return False

    cur_patch = pathlib.Path(git_worktree_get_git_dir()) / "rebase-apply" / "patch"

    fallback_apply_reset()
    ret = git_can_fail(
        f"apply --index --reject --recount {cur_patch}", stdout=stdout, stderr=stderr, env=env, start_new_session=True
    )
    if ret.returncode != 0:
        fallback_apply_reset()

        # record previously untracked files so we don't add them later
        untracked_files = []
        for l in git("status --porcelain").stdout.splitlines():
            if l[0] == "?" and l[1] == "?":
                f = pathlib.Path(l.split()[1])
                untracked_files += []

        patch_can_fail = run_wrapper("patch", capture=True, check=False)
        ret = patch_can_fail(f"-p1 -i {cur_patch}", stdout=stdout, stderr=stderr, env=env, start_new_session=True)
        if ret.returncode == 0:
            for l in git("status --porcelain").stdout.splitlines():
                f = pathlib.Path(l.split()[1])
                if l[0] == "?" and l[1] == "?" and f not in untracked_files:
                    git(f"add {f}")
                else:
                    git(f"add {f}")

    return ret.returncode == 0


def should_try_fuzzy(args, msg):
    if args.fuzzy is None:
        if sys.stdin.isatty():
            fuzzy = prompt_yesno(msg, default=True)
        else:
            fuzzy = False

        # cache reply for next times
        args.fuzzy = fuzzy

    return args.fuzzy


def fallback_apply_reset():
    git("reset --hard HEAD")
    status = git("status --porcelain").stdout.splitlines()

    # remove any untracked file left by git-apply or patch (*.rej, *.orig)
    for l in status:
        if l[0] == "?" and l[1] == "?" and (l.endswith(".rej") or l.endswith(".orig")):
            f = pathlib.Path(l.split()[1])
            f.unlink(missing_ok=True)


class GenbranchCmd(PileCommand):
    """
    Generate RESULT_BRANCH by applying patches from PILE_BRANCH on top of BASELINE
    """

    parser_epilog = (
        Config.help("genbranch")
        + """

Running without a setup in place:
  The genbranch command is usually run with a repository already configured for
  git-pile, however it is also possible to use --no-config to generate the
  result branch without a setup in place (e.g. "git pile --no-config genbranch
  -i -e path/to/patches").
"""
    )

    parser_formatter_class = argparse.RawTextHelpFormatter

    supports_no_config = True

    def init(self):
        self.parser.add_argument(
            "-b", "--branch", help="Use BRANCH to store the final result instead of RESULT_BRANCH", metavar="BRANCH", default=""
        )
        self.parser.add_argument(
            "-f",
            "--force",
            help="Always create RESULT_BRANCH, even if it's checked out in any path",
            action="store_true",
            default=False,
        )
        self.parser.add_argument(
            "-q", "--quiet", help="Quiet mode - do not print list of patches", action="store_true", default=False
        )
        self.parser.add_argument("-e", "--external-pile", help="Use external pile dir as input", default=None)
        self.parser.add_argument("--pile-rev", help="Use pile revision as input instead of current pile checkout")
        self.parser.add_argument(
            "-i",
            "--inplace",
            "--in-place",
            help="Generate branch in-place, enable conflict resolution and recovery: the current branch in the CWD is reset to the baseline commit and patches applied",
            action="store_true",
            dest="inplace",
            default=False,
        )
        self.parser.add_argument(
            "--fix-whitespace", help="Pass --whitespace=fix to git am to fix whitespace", action="store_true"
        )
        self.parser.add_argument("--no-fuzzy", action="store_false", dest="fuzzy", default=None)
        self.parser.add_argument(
            "--fuzzy",
            help="Allow to fallback to patch application with conflict solving. "
            "When using this option, git-pile will try to fallback to alternative "
            "patch application methods to avoid conflicts that can be solved by "
            "tools other than git-am. The final branch will not correspond to the "
            "pile and will need to be regenerated",
            action="store_true",
            dest="fuzzy",
            default=None,
        )
        self.parser.add_argument(
            "--dirty",
            help="Just apply the patches, do not create the corresponding commits",
            action="store_true",
            dest="dirty",
            default=False,
        )
        self.parser.add_argument(
            "-x", "--baseline", help="Ignoring baseline from pile, use whatever provided as argument", default=None
        )
        self.parser.add_argument("--no-cache", action="store_false", dest="use_cache")
        self.parser.add_argument(
            "--cache",
            help="Use cached information to avoid recreating commits. "
            "Default behavior is the to use cache if configuration "
            "pile.genbranch-use-cache is undefined or set to true.",
            action="store_true",
            dest="use_cache",
        )
        self.parser.set_defaults(use_cache=None)

    def run(self):
        return genbranch(self.config, self.args)
