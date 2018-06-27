#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1+

import argparse

try:
    import argcomplete
except ImportError:
    pass

from .helpers import run_wrapper

# external commands
git = run_wrapper('git')

arg_parser = None


def help(args):
    arg_parser.print_help()
    return 0


def parse_args(cmd_args):
    global arg_parser, args

    parser = argparse.ArgumentParser(
            description="Manage a pile of patches on top of git branches")
    subparsers = parser.add_subparsers()

    # help
    parser_help = subparsers.add_parser('help')
    parser_help.set_defaults(func=help)

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
