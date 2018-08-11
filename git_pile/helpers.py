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
