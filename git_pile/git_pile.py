#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1+

import argparse
import os
import os.path as op
import tempfile

try:
    import argcomplete
except ImportError:
    pass

from .helpers import run_wrapper

# external commands
git = run_wrapper('git', capture=True)

nul_f = open(os.devnull, 'w')


class Config:
    def __init__(self):
        self.dir = ""
        self.branch = ""
        self.pile_branch = ""
        self.remote_branch = ""
        self.tracking_branch = ""

        s = git(["config", "--get-regex", "pile\\.*"]).stdout.strip()
        for kv in s.split('\n'):
            key, value = kv.strip().split()
            # pile.*
            key = key[5:].replace('-', '_')
            setattr(self, key, value)

    def is_valid(self):
        return self.dir != '' and self.branch != '' and self.pile_branch != ''


def git_branch_exists(branch):
    return git("show-ref --verify --quiet refs/heads/%s" % branch, check=False).returncode == 0


def cmd_init(args):
    # TODO: check if already initialized
    # TODO: check if arguments make sense
    git("config pile.dir %s" % args.dir)
    git("config pile.pile-branch %s" % args.pile_branch)
    git("config pile.branch %s" % args.branch)
    git("config pile.tracking-branch %s" % args.tracking_branch)
    if args.remote_branch:
        git("config pile.remote-branch=%s" % args.remote_branch)

    config = Config()

    # TODO: remove prints
    print("dir=%s\npile-branch=%s\nremote-branch=%s\ntracking-branch=%s\nbranch=%s" %
          (config.dir, config.pile_branch, config.remote_branch, config.tracking_branch,
           config.branch))
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
                rev = git("rev-parse %s" % config.tracking_branch).stdout.strip()
                f.write("BASELINE=%s" % rev)
            git("-C %s add -A" % d)
            git(["-C", d, "commit", "-m", "Initial git-pile configuration"])

            # Temporary repository created, now let's fetch and create our branch
            git("fetch %s master:%s" % (d, config.pile_branch), stdout=nul_f, stderr=nul_f)
            git("worktree add --checkout %s %s" % (config.pile_branch, config.dir),
                stdout=nul_f, stderr=nul_f)

    return 0


def parse_args(cmd_args):
    parser = argparse.ArgumentParser(
        description="Manage a pile of patches on top of git branches")
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
        "-t", "--tracking-branch",
        help="Base remote or local branch on top of which the patches from PILE_BRANCH should be applied (default: %(default)s)",
        metavar="TRACKING_BRANCH",
        default="master")
    parser_init.add_argument(
        "-b", "--branch",
        help="Branch to be created when applying patches from PILE_BRANCH on top of TRACKING_BRANCH (default: %(default)s",
        metavar="BRANCH",
        default="internal")
    parser_init.add_argument(
        "-r", "--remote-branch",
        help="TODO: Remote branch to which patches will be pushed (default: empty - configure it later with `git config pile.remote`)",
        metavar="REMOTE",
        default="")
    parser_init.set_defaults(func=cmd_init)

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
