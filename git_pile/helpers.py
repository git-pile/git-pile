#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1+

from subprocess import run


class run_wrapper:
    def __init__(self, cmd):
        self.cmd = cmd

    def __call__(self, s, *args, **kwargs):
        run([self.cmd] + s.split(), *args, **kwargs)
