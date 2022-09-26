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
import subprocess

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

    def validate_structure(self, warn_non_patches=True):
        """
        Validate the structure of the pile branch.

        Note that the content of files is not checked.

        If a problem is found, ``PileError`` is raised with a message explaining
        it.

        If ``warn_non_patches`` is true, a warning is issued if non-patch files
        are found. Note that files under sub-directories or hidden files are
        ignored and not considered to be non-patch files.
        """
        has_non_patches = False
        missing_files = {"series", "config"}

        for filename, objecttype in self.__reader.ls(include_type=True):
            if objecttype == "tree":
                # Allow directories to contain project-specific files
                continue
            elif objecttype != "blob":
                raise PileError(f"unexpected tree entry type for {filename!r} in {self.__loc_phrase()}: {objecttype}")

            if filename.startswith("."):
                # Allow hidden files to contain project-specific configuration
                continue

            if filename in missing_files:
                missing_files.remove(filename)
            elif not filename.endswith(".patch"):
                has_non_patches = True

        if missing_files:
            missing_files_str = ",".join(sorted(missing_files))
            raise PileError(f"missing files in {self.__loc_phrase()}: {missing_files_str}")

        if has_non_patches and warn_non_patches:
            helpers.warn(f"non-patch files found in {self.__loc_phrase()}")

    def __loc_phrase(self):
        if self.__rev:
            return f"pile revision {self.__rev}"
        else:
            return f'pile directory "{self.__path}"'


class PileError(Exception):
    pass


_git = helpers.run_wrapper("git", capture=True)


class _FileReader(abc.ABC):
    """
    Abstract class to provide "file-reading" functionality to the ``Pile`` class.

    Methods using paths receive them as ``*path`` parameters. Concrete
    implementations to the necessary joining and other operations to correctly
    use them.
    """

    @abc.abstractmethod
    def ls(self, include_type=False):
        """
        Yield each entry found in the pile branch.

        By default, the filename for each entry is yielded. If ``include_type``
        is true, then a 2-element tuple ``(filename, objecttype)`` is yielded,
        with ``objecttype`` being the git object type for the entry.

        Implementations backed by file system directories must use the same
        object type that git would use when for the corresponding tree object.
        If the directory under a git repository, then ignore rules must be
        obeyed.
        """
        raise NotImplementedError()


class _PathReader(_FileReader):
    def __init__(self, path):
        self.__path = pathlib.Path(path)

    def ls(self, include_type=False):
        for p in self.__filter_git_ignored(self.__path.glob("*")):
            if not include_type:
                yield p.name
            else:
                objecttype = "tree" if p.is_dir() else "blob"
                yield p.name, objecttype

    def __filter_git_ignored(self, path_iter):
        try:
            _git(["-C", str(self.__path), "rev-parse", "--show-toplevel"])
        except subprocess.CalledProcessError:
            yield from path_iter

        names = [p.name for p in path_iter]

        try:
            ignored = set(
                _git(
                    ["-C", str(self.__path), "check-ignore", "--stdin", "-z"],
                    text=True,
                    input="\x00".join(names),
                ).stdout.split("\x00")
            )
        except subprocess.CalledProcessError as e:
            if e.returncode == 1:
                ignored = set()
            else:
                raise

        for name in names:
            if name not in ignored:
                yield self.__path / name


class _RevReader(_FileReader):
    def __init__(self, rev):
        self.__rev = rev

    def ls(self, include_type=False):
        if include_type:
            fmt = "%(objecttype) %(path)"
        else:
            fmt = "%(path)"
        out = _git(["ls-tree", "-z", "--full-tree", f"--format={fmt}", self.__rev]).stdout

        for entry in out.rstrip("\x00").split("\x00"):
            if include_type:
                objecttype, name = entry.split(" ", maxsplit=1)
                yield name, objecttype
            else:
                yield entry
