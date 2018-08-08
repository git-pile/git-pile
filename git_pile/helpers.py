#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1+

import os

import subprocess


class run_wrapper:
    def __init__(self, cmd, env_default=None, capture=False, check=True):
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

    def __call__(self, s, *args, **kwargs):
        capture = kwargs.pop("capture", self.capture)

        if capture:
            if "stdout" not in kwargs:
                kwargs["stdout"] = subprocess.PIPE
            if "encoding" not in kwargs:
                kwargs["encoding"] = "utf-8"

        kwargs["check"] = kwargs.get("check", self.check)

        if isinstance(s, str):
            l = s.split()
        else:
            l = s

        return subprocess.run([self.cmd] + l, *args, **kwargs)


class subcmd:
    names = []

    def add(f):
        subcmd.names.append(f.__name__)
        return f

    def list():
        return subcmd.names
