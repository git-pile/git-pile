# SPDX-License-Identifier: LGPL-2.1+
"""
This module provides two classes:

    1. ``PileCLI``, which implements `git-pile`'s CLI handling entry point with
       the ``argparse`` module.

    2. ``PileCommand``, which must be subclassed to implement pile commands. The
       subclass must then be added to the ``PileCLI`` instance with the method
       ``add_command()`` in order to be exposed to the user. That method creates
       a subparser for the command.

Example::

  >>> class FooBarCmd(PileCommand):
  ...     '''
  ...     One-liner summary for the command.
  ...
  ...     Detailed description for the command goes in the subsequent
  ...     paragraphs.
  ...     '''
  ...
  ...     def init(self):
  ...         self.parser.add_argument("--foo", action="store_true")
  ...         self.parser.add_argument("--bar", action="append")
  ...
  ...     def run(self):
  ...         print(f"--foo={self.args.foo}")
  ...         print(f"--bar={self.args.bar}")

  >>> cli = PileCLI(None)  # Using None as config for the sake of the example
  >>> cli.add_command(FooBarCmd)
  >>> args = cli.parse_args(["foo-bar", "--foo", "--bar", "hello", "--bar", "world"])
  >>> cli.run(args)
  --foo=True
  --bar=['hello', 'world']


Notes regarding ``PileCommand`` subclasses:

  - The command name is automatically extracted from the class name,
    transforming the camel case into lowercase words separated by dashes. You
    can provide a custom name with the ``name`` class attribute.

  - The class' docstring is used by default as the ``description`` keyword for
    ``add_parser()``. You can override that by passing a custom description in
    the ``parser_description`` class attribute.

  - The ``help`` keyword for ``add_parser()`` call is extracted as the first
    line of the derived description (see above). You can override that with the
    ``parser_help`` class attribute.

  - Any class attribute with name prefixed by "parser_" will be passed as a
    keyword to the call to ``add_parser()``. For example, the value of
    ``parser_epilog`` will be passed as the ``epilog`` keyword.

  - The class attribute ``supports_no_config`` should be set True for commands
    that are supposed to handle calls with option ``--no-config`` passed.

  - The class attribute ``skip_config_normalize`` should be set True for commands
    that should not have the config object being automatically normalized (i.e.
    have ``Config.normalized()`` called).

  - There are two main methods expected to be implemented by subclasses:

    1. ``init()``: this is where initialization (like adding arguments) is done.
       This method is called when the command is added to a ``PileCLI``
       instance.

    2. ``run()``: this is the method called by ``PileCLI`` when to run this
       command.

  - A ``PileCommand`` instance has access to the following attributes:

    - ``args``: the ``argparse.Namespace`` object containing the CLI arguments.
      This is available only during the execution of the command (i.e. inside
      the method ``run()``).

    - ``cli``: the ``PileCLI`` instance owning the command.

    - ``config``: the configuration object passed to the ``PileCLI`` instance
      owning the command.

    - ``parser``: the subparser created for the command.

"""
import argparse
import sys
import textwrap

from . import __version__
from . import config as configmod
from . import helpers


class PileCommand:
    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        if not hasattr(cls, "name"):
            cls.name = cls.__default_cmd_name()

        if not hasattr(cls, "parser_description"):
            cls.parser_description = textwrap.dedent(cls.__doc__)

        if not hasattr(cls, "parser_help"):
            cls.parser_help, _, _ = cls.parser_description.strip().partition("\n")

        if not hasattr(cls, "supports_no_config"):
            cls.supports_no_config = False

        if not hasattr(cls, "skip_config_normalize"):
            cls.skip_config_normalize = False

    @classmethod
    def __default_cmd_name(cls):
        name = cls.__name__
        if name.endswith("Cmd"):
            name = name[:-3]
        name = name[0].lower() + "".join(f"-{c.lower()}" if c.isalpha() and c.isupper() else c for c in name[1:])
        return name

    def run(self):
        raise NotImplementedError()


class PileCLI:
    def __init__(self, config=None):
        self.config = config
        self.parser = argparse.ArgumentParser(
            description=PILE_COMMAND_DESCRIPTION,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        self.parser.add_argument(
            "-v",
            "--version",
            action="version",
            version=f"git-pile {__version__}",
        )
        self.parser.add_argument(
            "--no-config",
            help="""
            Skip loading the configuration values from git config. This is
            useful for pile commands that do not require a complete pile setup
            (or for when you know what you are doing and want to do things in an
            unorthodox way).
            """,
            action="store_true",
        )

        self.subparsers = self.parser.add_subparsers(title="Commands", dest="command")

    def __onetime_config_setup(self, args, cmd):
        self.__onetime_config_setup = lambda *_: None

        if not self.config:
            if args.no_config and not cmd.supports_no_config:
                helpers.warn(f"subcommand {args.command} is not supposed to be called with --no-config")

            self.config = configmod.Config(skip_load=args.no_config)

            if not cmd.skip_config_normalize and not args.no_config:
                if not self.config.normalize(self.config.root):
                    helpers.fatal("Could not find checkout for result-branch / pile-branch")

    def add_command(self, cmd_cls):
        cmd = cmd_cls()

        parser_kw = {k[7:]: v for k, v in cmd_cls.__dict__.items() if k.startswith("parser_")}
        parser = self.subparsers.add_parser(cmd_cls.name, **parser_kw)

        cmd.parser = parser
        cmd.cli = self

        if hasattr(cmd, "init"):
            cmd.init()

        parser.add_argument(
            "--debug",
            help="Turn on debugging output",
            action="store_true",
            default=False,
        )
        parser.set_defaults(cmd_object=cmd)

    def parse_args(self, argv=sys.argv[1:]):
        return self.parser.parse_args(argv)

    def run(self, args):
        try:
            cmd = args.cmd_object
        except AttributeError:
            self.parser.print_help()
            return 1

        self.__onetime_config_setup(args, cmd)

        # Save args.debug value, since args is mutable.
        enable_debug = args.debug
        if enable_debug:
            saved_debug_flag = helpers.get_debugging()
            helpers.set_debugging(True)

        if hasattr(cmd, "args"):
            raise Exception("command recursion not supported")

        cmd.args = args
        cmd.config = self.config

        try:
            return cmd.run()
        finally:
            del cmd.args
            del cmd.config
            if enable_debug:
                helpers.set_debugging(saved_debug_flag)


PILE_COMMAND_DESCRIPTION = """
Manage a pile of patches on top of a git branch

git-pile helps to manage a long running and always changing list of patches on
top of git branch. It is similar to quilt, but aims to retain the git work flow
exporting the final result as a branch. The end result is a configuration setup
that can still be used with it.

There are 2 branches and one commit head that are important to understand how
git-pile works:

    PILE_BRANCH: where to keep the patches and track their history
    RESULT_BRANCH: the result of applying the patches on top of (changing) base

The changing base is a commit that continues to be updated (either as a fast-forward
or as non-ff) onto where we want to be based off. This changing head is here
called BASELINE.

    BASELINE: where patches will be applied on top of.

This is a typical scenario git-pile is used in which BASELINE currently points
to a "master" branch and RESULT_BRANCH is "internal" (commit hashes here
onwards are fictitious).

A---B---C 3df0f8e (master)
         \\
          X---Y---Z internal

PILE_BRANCH is a branch containing this file hierarchy based on the above
example:

series  config  X.patch  Y.patch  Z.patch

The "series" and "config" files are there to allow git-pile to do its job and
are retained for compatibility with quilt and qf. For that reason the latter is
also where BASELINE is stored/read when it's needed. git-pile exposes commands
to convert back and forth between RESULT_BRANCH and the files on PILE_BRANCH.
Those commands allows to save the history of the patches when the BASELINE
changes or patches are added, modified or removed in RESULT_BRANCH. Below is a
example in which BASELINE may evolve to add more commit from upstream:

          D---E master
         /
A---B---C 3df0f8e
         \\
          X---Y---Z internal

After a rebase of the RESULT_BRANCH we will have the following state, in
which X', Y' and Z' denote the rebased patches. They may have possibly
changed to solve conflicts or to apply cleanly:

A---B---C---D---E 76bc046 (master)
                 \\
                  X'---Y'---Z' internal

In turn, PILE_BRANCH will store the saved result:

series  config  X'.patch  Y'.patch  Z'.patch
"""
