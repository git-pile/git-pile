#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1+

import os
import subprocess
import sys


class run_wrapper:
    def __init__(self, cmd, env_default=None, capture=False, check=True, print_error_as_ignored=False):
        """
        Wrap @cmd into a cmd() function. If env_default is not None,
        cmd is considered to be an environment variable and if it's
        not set, the default value in env_default is used
        """

        if env_default is not None:
            val = os.getenv(cmd, env_default)
        else:
            val = cmd

        self.cmd = val
        self.capture = capture
        self.check = check
        self.print_error_as_ignored = print_error_as_ignored


    def __call__(self, s, *args, **kwargs):
        capture = kwargs.pop("capture", self.capture)

        if capture:
            if "stdout" not in kwargs:
                kwargs["stdout"] = subprocess.PIPE
            if "encoding" not in kwargs:
                kwargs["encoding"] = "utf-8"

        if self.print_error_as_ignored:
            kwargs["stderr"] = subprocess.PIPE
            if "encoding" not in kwargs:
                kwargs["encoding"] = "utf-8"

        kwargs["check"] = kwargs.get("check", self.check)

        if isinstance(s, str):
            l = s.split()
        else:
            l = s

        ret = subprocess.run([self.cmd] + l, *args, **kwargs)

        if self.print_error_as_ignored and ret.returncode != 0:
            print("Ignoring failed command: '%s %s'" % (self.cmd, " ".join(l)))
            print("\t", ret.stderr, end="", file=sys.stderr)

        return ret


class subcmd:
    names = []

    def add(f):
        subcmd.names.append(f.__name__)
        return f

    def list():
        return subcmd.names


# @f is a file-like object, list or anything that supports being iterated over.
# Only the result of `git diff -p --raw`  is really parsed
# Example input:
#
# :100644 100644 eeac82c f0bb378 R093     0001-Add-platform-3-2.patch   0001-Add-platform-3.5.patch
# :000000 100644 0000000 0000000 A        0001-Add-xyz.patch
# :000000 100644 0000000 0000000 A        0001-change-xyz.patch
# :000000 100644 0000000 0000000 A        0001-move-readme.patch
# :100644 100644 0000000 0000000 M        series
# 
# diff --git a/0001-move-readme.patch b/0001-move-readme.patch
# ...
#
#
# It stops parsing on the first blank line so the user can continue parsing the
# rest as a normal diff
# 
# Return: a list of tuples with (action, new_fileame). Example:
# [
#  ("R", "0001-Add-platform-3.5.patch"),
#  ("A", "0001-Add-xyz.patch"),
#  ("A", "0001-change-xyz.patch"),
#  ("A", "0001-move-readme.patch"),
#  ("M", "series")
# ]
def parse_raw_diff(f):
    changes = []
    for l in f:
        l = l.rstrip()
        if not l:
            break

        state, *files = l.split("\t")
        # sanity checks
        if not state or len(state) < 5 or not files or len(files) > 2:
            raise Exception("Doesn't know how to parse line: '%s'" % l)

        action = state.split(" ")[4][0]

        # we are only interested in the new name (the last entry in the line)
        t = action, files[-1]

        changes.append(t)

    return changes


def info(s, *args, **kwargs):
    color = kwargs.pop("color", True)
    if color:
        sl = ["‣\033[0;1;39m", s, *args, "\033[0m"]
    else:
        sl = [s, *args]

    print(*sl, **kwargs)
