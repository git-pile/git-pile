#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1+

import os
import shlex
import subprocess
import sys

from contextlib import contextmanager

debug_run = False
fatal_behavior = "exit"

def set_debugging(val):
    global debug_run
    debug_run = val


def set_fatal_behavior(s):
    global fatal_behavior
    fatal_behavior = s


# Like open(), but reserves file == "-", file == "" or file == None for stdin
def open_or_stdin(file, *args, **kwargs):
    if not file or file == "-":
        # we can't simply return sys.stdin as a file object may be used
        # as a context manager, so f would implicitely be closed and fail
        # a second call. We never want to implicitely close stdin
        kwargs["closefd"] = False
        return open(sys.stdin.fileno(), *args, **kwargs)

    return open(file, *args, **kwargs)


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
        print_error_as_ignored = kwargs.pop("print_error_as_ignored", self.print_error_as_ignored)

        if capture:
            if "stdout" not in kwargs:
                kwargs["stdout"] = subprocess.PIPE
            if "universal_newlines" not in kwargs:
                kwargs["universal_newlines"] = True

        if print_error_as_ignored:
            kwargs["stderr"] = subprocess.PIPE
            if "universal_newlines" not in kwargs:
                kwargs["universal_newlines"] = True

        kwargs["check"] = kwargs.get("check", self.check)

        if isinstance(s, str):
            l = s.split()
        else:
            l = s

        l.insert(0, self.cmd)

        cmd_debug = ' '.join(shlex.quote(x) for x in l)
        if debug_run:
            print('+ ' + cmd_debug, file=sys.stderr)

        ret = subprocess.run(l, *args, **kwargs)

        if self.print_error_as_ignored and ret.returncode != 0:
            print("Ignoring failed command: '{}'".format(cmd_debug))
            print("\t", ret.stderr, end="", file=sys.stderr)

        return ret


class subcmd:
    names = []

    def add(f):
        subcmd.names.append(f.__name__)
        return f

    def list():
        return subcmd.names


def info(s, *args, **kwargs):
    color = kwargs.pop("color", True)
    if color:
        sl = ["‣\033[0;1;39m", s, *args, "\033[0m"]
    else:
        sl = [s, *args]

    print(*sl, **kwargs)

class FatalException(Exception):
    """Fatal exception, can't continue"""
    pass


def fatal(s, *args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    print("fatal:", s, *args, **kwargs)
    if fatal_behavior == "exit":
        sys.exit(1)
    raise FatalException()


def error(s, *args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    print("error:", s, *args, **kwargs)


def warn(s, *args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    print("warning:", s, *args, **kwargs)


def orderedset(it):
    return dict.fromkeys(it).keys()


def prompt_yesno(question, default):
    if default is None:
        choices = ' [y/n]: '
        default_reply = None
    elif not default:
        choices = ' [y/N]: '
        default_reply = 'n'
    else:
        choices = ' [Y/n]: '
        default_reply = 'y'

    reply = None
    while reply is None:
        reply = str(input(question + choices)).lower().strip() or default_reply

    if reply[0] == 'y':
        return True
    if reply[0] == 'n':
        return False
    
    return default


@contextmanager
def pushdir(d, oldd):
    if not oldd:
        oldd = os.getcwd()
    os.chdir(d)
    try:
        yield
    finally:
        os.chdir(oldd)
