#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1+

import os

from subprocess import run


class run_wrapper:
    def __init__(self, cmd, env_default=None):
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

    def __call__(self, s, *args, **kwargs):
        run([self.cmd] + s.split(), *args, **kwargs)


class subcmd:
    names = []

    def add(f):
        subcmd.names.append(f.__name__)
        return f

    def list():
        return subcmd.names
