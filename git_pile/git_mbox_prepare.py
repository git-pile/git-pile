#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1+

import argparse

try:
    import argcomplete
except ImportError:
    pass

args = None


def parse_args():
    global args

    parser = argparse.ArgumentParser(
        description="Prepare a mbox for use by git - improved version over GIT-MAILSPLIT(1)")

    parser.add_argument(
        "-o", "--output", help="Directory in which to place final patches",
        metavar="DIR")

    group = parser.add_argument_group("Required arguments")
    group.add_argument("mbox", help="mbox file to process", metavar="PATH")

    try:
        argcomplete.autocomplete(parser)
    except NameError:
        pass
    args = parser.parse_args()


def main():
    parse_args()
