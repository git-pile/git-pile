#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1+

import argparse
import sys

try:
    import argcomplete
except ImportError:
    pass

from .helpers import run_wrapper, subcmd

# external commands
git = run_wrapper('git')

arg_parser = None


@subcmd.add
def test():
    print("test")


@subcmd.add
def test2():
    print("test2")


@subcmd.add
def help():
    arg_parser.print_help()
    sys.exit(0)


def parse_args(cmd_args):
    global arg_parser

    parser = argparse.ArgumentParser(
            description="Manage a pile of patches on top of git branches")
    group = parser.add_argument_group("Commands")
    group.add_argument("action", choices=subcmd.list())

    try:
        argcomplete.autocomplete(parser)
    except NameError:
        pass
    args = parser.parse_args(cmd_args)
    arg_parser = parser

    if args.action:
        globals()[args.action]()


def main(*cmd_args):
    parse_args(cmd_args)

    return 0
