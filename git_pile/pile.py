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
import collections
import pathlib
import subprocess

from .helpers import (
    git,
    warn,
)


class Pile:
    """
    Class responsible for representing the pile tree.
    """

    def __init__(self, *, rev=None, path=None, baseline=None, rev_repo_path=None):
        """
        Initialize the object from either a revision or a path in the file system.

        The keywords ``rev`` and ``path`` are mutually exclusive:

        - If ``rev`` is used, it must point to a git tree-ish object containing
          a tree representing a checkout of the pile branch. In most cases,
          ``rev`` will name a commit in the pile branch.

        - If ``path`` is used, then it must point to a directory representing a
          checkout of the pile branch. The directory does not have to be tracked
          by git, but must match the structure of the pile branch.

        The keyword ``baseline`` can be used to provide an alternative baseline
        to be used. If not ``None``, it causes ``self.baseline()`` to always
        return the passed value.

        If ``rev`` belongs to a git repository that does not track the the
        current directory, the keyword ``rev_repo_path`` can be passed to
        indicate a directory to change into before issuing git commands.
        """
        if rev and path:
            raise Exception("parameters path and rev are mutually exclusive")

        if not rev and not path:
            raise Exception("missing rev or path parameters")

        self.__rev = rev
        self.__path = path
        self.__reader = _RevReader(rev, rev_repo_path) if rev else _PathReader(path)
        self.__config = None
        self.__baseline_override = baseline

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
            warn(f"non-patch files found in {self.__loc_phrase()}")

    def baseline(self):
        """
        Return the baseline for the pile.

        This returns the sha1 for the baseline if found in the pile config,
        otherwise ``None`` is returned.

        Note that the baseline is cached for subsequent calls. If it is desired
        to get the possibly refreshed value, it is necessary to call
        ``self.read_config()`` to refresh the internal cache.
        """
        if self.__baseline_override is not None:
            return self.__baseline_override
        return self.__get_config().get("BASELINE")

    def read_config(self):
        """
        Read the ``config`` file.

        This method can be used to refresh any cached configuration data.
        """
        self.__get_config(refresh=True)

    def series(self):
        """
        Yield a PilePatch object for each patch found in the pile series.
        """
        for line in self.__reader.text("series").splitlines():
            line = line.strip()
            if not line or line[0] == "#":
                continue
            yield PilePatch(line, self.__reader)

    def __loc_phrase(self):
        if self.__rev:
            return f"pile revision {self.__rev}"
        else:
            return f'pile directory "{self.__path}"'

    def __get_config(self, refresh=False):
        if self.__config is not None and not refresh:
            return self.__config

        data = {}
        for i, line in enumerate(self.__reader.text("config").splitlines()):
            name, equals, value = line.partition("=")
            name = name.strip()
            value = value.strip()
            if "" in (name, equals, value):
                raise PileError(f"invalid config at line {i + 1}: expecting string in the format <KEY>=<VALUE>")
            data[name] = value

        self.__config = data
        return self.__config


class PilePatch:
    def __init__(self, name, reader):
        self.name = name
        self.__reader = reader

    def sha1(self):
        return self.__reader.sha1(*pathlib.Path(self.name).parts)


class PileError(Exception):
    pass


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

    @abc.abstractmethod
    def text(self, *path):
        """
        Read and return the content of the file pointed by ``path`` as a string.

        This must raise a FileNotFoundError if the file is not found.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def sha1(self, *path):
        """
        Generate the git sha-1 digest for the file pointed by ``path``.

        This must raise a FileNotFoundError if the file is not found.
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

    def text(self, *path):
        return self.__path.joinpath(*path).read_text()

    def sha1(self, *path):
        return git(["hash-object", "--", str(self.__path.joinpath(*path))]).stdout.strip()

    def __filter_git_ignored(self, path_iter):
        try:
            git(["-C", str(self.__path), "rev-parse", "--show-toplevel"])
        except subprocess.CalledProcessError:
            yield from path_iter

        names = [p.name for p in path_iter]

        try:
            ignored = set(
                git(
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
    def __init__(self, rev, repo_path):
        self.__rev = rev
        self.__repo_path = repo_path
        # Leverage git revisions immutability to cache the result of ls-tree.
        # This is specially useful when __ls_path() is called multiple times for
        # different direct children of a very broad tree (e.g. a pile directory
        # containing thousands of patches).
        self.__ls_tree_cache = None

    def ls(self, include_type=False):
        for name, objecttype, _ in self.__ls_tree().values():
            if include_type:
                yield name, objecttype
            else:
                yield name

    def text(self, *path):
        # `git show <rev>:<path>` does not provide a documented way of verifying
        # that it failed because <path> does not exist under <rev>, so we need
        # to call __ls_path() to ensure a FileNotFoundError is properly raised
        # if necessary.
        self.__ls_path(path)
        gitpath = "/".join(path)
        revspec = f"{self.__rev}:{gitpath}"
        return self.__git(["show", revspec]).stdout

    def sha1(self, *path):
        _, _, sha1 = self.__ls_path(path)
        return sha1

    def __git(self, *cmd, **kw):
        if self.__repo_path:
            kw["cwd"] = self.__repo_path

        return git(*cmd, **kw)

    def __ls_path(self, path, fmt=""):
        if len(path) == 1:
            # Optimize for a direct child so as to which will used cached info
            # if available.
            info = self.__ls_tree()
        else:
            info = self.__ls_tree(path)
        gitpath = "/".join(path)
        try:
            return info[gitpath]
        except KeyError:
            raise FileNotFoundError(f"path {gitpath!r} not found under revision {self.__rev}")

    def __ls_tree(self, path=None):
        if self.__ls_tree_cache is not None and path is None:
            return self.__ls_tree_cache

        cmd = [
            "ls-tree",
            "-z",
            "--full-tree",
            self.__rev,
        ]
        if path is not None:
            gitpath = "/".join(path)
            cmd.append(gitpath)

        info = collections.OrderedDict()
        for entry in self.__git(cmd).stdout.rstrip("\x00").split("\x00"):
            _, objecttype, sha1, name = entry.split(maxsplit=3)
            info[name] = name, objecttype, sha1

        if path is None:
            self.__ls_tree_cache = info

        return info
