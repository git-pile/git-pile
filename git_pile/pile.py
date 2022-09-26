# SPDX-License-Identifier: LGPL-2.1+
"""
This module provides the ``Pile`` class, responsible for representing the
content of the pile branch.

A checkout of the pile branch requires the following files:

- ``config``: file containing configuration data. Currently only the
  baseline is stored in this file.

- ``series``: file containing the sequence of patches that would be used
  for generating the result branch. Each line is the name of the file
  containing the respective patch for the sequence.

- ``*.patch``: patch files pointed by ``series``.

This module allows working not only with git revisions of a pile branch, but
with directories representing the checkout of a pile branch as well (see
documentation for ``Piles``'s constructor). Throughout the documentation for
this module, unless the context makes the difference clear, the term "pile
branch" will be used to refer to the required structure, abstracting away
whether it comes from a git tree-ish object or directory in the file system.
"""
import abc
import pathlib

from . import helpers


class Pile:
    """
    Class responsible for representing the pile tree.
    """

    def __init__(self, *, rev=None, path=None):
        """
        Initialize the object from either a revision or a path in the file system.

        The keywords ``rev`` and ``path`` are mutually exclusive:

        - If ``rev`` is used, it must point to a git tree-ish object containing
          a tree representing a checkout of the pile branch. In most cases,
          ``rev`` will name a commit in the pile branch.

        - If ``path`` is used, then it must point to a directory representing a
          checkout of the pile branch. The directory does not have to be tracked
          by git, but must match the structure of the pile branch.
        """
        if rev and path:
            raise Exception("parameters path and rev are mutually exclusive")

        if not rev and not path:
            raise Exception("missing rev or path parameters")

        self.__rev = rev
        self.__path = path
        self.__reader = _RevReader(rev) if rev else _PathReader(path)


_git = helpers.run_wrapper("git", capture=True)


class _FileReader(abc.ABC):
    """
    Abstract class to provide "file-reading" functionality to the ``Pile`` class.

    Methods using paths receive them as ``*path`` parameters. Concrete
    implementations to the necessary joining and other operations to correctly
    use them.
    """

    pass


class _PathReader(_FileReader):
    def __init__(self, path):
        self.__path = pathlib.Path(path)


class _RevReader(_FileReader):
    def __init__(self, rev):
        self.__rev = rev
