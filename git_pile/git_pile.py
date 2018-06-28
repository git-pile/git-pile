#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1+

import argparse

try:
    import argcomplete
except ImportError:
    pass

from .helpers import run_wrapper

# external commands
git = run_wrapper('git', capture=True)

arg_parser = None


class Config:
    def __init__(self):
        self.dir = git("config --get pile.dir").stdout.strip()
        self.branch = git("config --get pile.branch").stdout.strip()
        self.remote_branch = git("config --get pile.remote-branch").stdout.strip()

    def is_valid(self):
        return self.dir != '' and self.branch != ''

def init(args):
    # TODO: check if already initialized
    # TODO: check if arguments make sense
    git("config pile.dir %s" % args.dir)
    git("config pile.branch %s" % args.branch)
    if args.remote_branch:
        git("config pile.remote-branch=%s" % args.remote_branch)

    config = Config()

    # TODO: remove prints
    print("dir=%s\nbranch=%s\nremote-branch=%s" %
          (config.dir, config.branch, config.remote_branch))
    print("is-valid=%s" % config.is_valid())

    return 0


def parse_args(cmd_args):
    global arg_parser, args

    parser = argparse.ArgumentParser(
        description="Manage a pile of patches on top of git branches")
    subparsers = parser.add_subparsers()

    # init
    parser_init = subparsers.add_parser('init')
    parser_init.add_argument(
        "-d", "--dir",
        help="Directory in which to place patches (default: %(default)s)",
        metavar="DIR",
        default="pile")
    parser_init.add_argument(
        "-b", "--branch",
        help="Branch name to use for patches (default: %(default)s)",
        metavar="BRANCH",
        default="pile")
    parser_init.add_argument(
        "-r", "--remote-branch",
        help="Remote branch to which patches will be pushed (default: empty - configure it later with `git config pile.remote`)",
        metavar="REMOTE",
        default="")
    parser_init.set_defaults(func=init)

    try:
        argcomplete.autocomplete(parser)
    except NameError:
        pass

    args = parser.parse_args(cmd_args)
    arg_parser = parser

    return args


def main(*cmd_args):
    args = parse_args(cmd_args)
    return args.func(args)
