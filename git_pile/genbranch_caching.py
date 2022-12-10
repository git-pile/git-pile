# SPDX-License-Identifier: LGPL-2.1+
"""
This module provides the class ``GenbranchCache``, which provides caching
functionality for genbranch.

The cached information is composed of trees matching pile patches with commit
objects. This cache is used by ``GenbranchCache.search_best_base()`` to keep a
genbranch operation from unnecessarily regenerating commits objects. More
information about the tree structure can be found in the documentation for the
internal class ``_Node``.
"""
import collections
import logging
import pathlib
import pickle
import subprocess
import tempfile

from .helpers import git


class GenbranchCache:
    """
    Class responsible for maintaining cache for genbranch.

    The cache is loaded by instantiating the class, can be updated with
    ``self.update()`` and saved back to the file system with ``self.save()``.

    The method ``self.search_best_base()`` should be used to find the best
    starting point for applying patches from a pile.
    """

    def __init__(self, path, committer_ident=None):
        """
        Initialize the cache by loading from ``path``.

        If ``path`` does not exist or an error happens during the load, an empty
        cache is initialized. In the case of the latter, a warning is also
        issued.

        If passed, ``committer_ident`` must be the output of calling the command
        "git var GIT_COMMITTER_IDENT". If the parameter is omitted, that command
        is called internally. This is used to select different trees based on
        the committer identity (date information in the string is ignored).
        """
        self.__path = pathlib.Path(path)
        self.__cache_data = _CacheData.load(self.__path)

        if not committer_ident:
            committer_ident = git(["var", "GIT_COMMITTER_IDENT"]).stdout
        # Drop the date information from committer_ident
        self.__committer_ident = committer_ident.strip().rsplit(maxsplit=2)[0]

        if self.__committer_ident not in self.__cache_data.trees:
            self.__cache_data.trees[self.__committer_ident] = _Node(None)
        self.__root = self.__cache_data.trees[self.__committer_ident]

    def search_best_base(self, pile, baseline=None):
        """
        Search for the best starting point for a genbranch operation.

        The parameter ``pile`` is used to get the series of patches for the
        genbranch operation. The parameter ``baseline`` defaults
        ``pile.baseline()`` and the caller can use it to provide an alternative
        baseline commit.

        This method uses cached information from previous genbranch runs to find
        the latest patch from a pile series that already has an existing commit.

        The returned value is the tuple ``(commit, offset)``, with ``commit``
        being the sha-1 hash of the commit to be used as starting point and
        ``offset`` being the index from which patches from the pile should be
        really applied. In other words, given ``l`` as the series of patches of
        ``pile``, the returned value says that genbranch says that the commits
        for patches in ``l[0:offset]`` already exist and that only the patches
        in ``l[offset:]`` need to be applied using ``commit`` as starting point.

        If no suitable commit exists, then ``(baseline, 0)`` is returned.
        """
        if not baseline:
            baseline = pile.baseline()

        try:
            nodes = [self.__root.children[baseline]]
        except KeyError:
            return baseline, 0

        for k in (p.sha1() for p in pile.series()):
            try:
                nodes.append(nodes[-1].children[k])
            except KeyError:
                break

        # Do a binary search to minimize calls to `git cat-file`.
        # The following algorithm has the following invariants:
        #
        #   1) all nodes in ``node[0:base + 1]`` have existing commit objects.
        #   2) all nodes in ``node[head + 1:]`` do not have existing commit
        #      objects.
        #
        # At the end of the loop, we will have ``base == head``, which means
        # that any node after ``base`` (or ``head``) will not have existing
        # commit objects, making ``node[base].commit`` the best existing
        # baseline for genbranch.
        base = 0
        head = len(nodes) - 1
        while base < head:
            i = (base + head + 1) // 2
            try:
                git(["cat-file", "-e", nodes[i].commit], stderr=subprocess.DEVNULL)
            except subprocess.CalledProcessError:
                head = i - 1
            else:
                base = i

        return nodes[base].commit, base

    def update(self, pile, head):
        """
        Update the cache for commits created for patches of a pile.

        Given ``head`` as the tip revision for the result of a genbranch
        operation on ``pile``, this method updates the cache tree to store the
        commit hashes for each patch in ``pile``'s series.
        """
        baseline = pile.baseline()
        series_hashes = (p.sha1() for p in pile.series())
        commits = git(["rev-list", "--reverse", f"{baseline}..{head}"]).stdout.splitlines()

        if baseline not in self.__root.children:
            self.__root.children[baseline] = _Node(baseline)

        node = self.__root.children[baseline]
        for patch_sha1, commit in zip(series_hashes, commits):
            if patch_sha1 not in node.children or node.children[patch_sha1].commit != commit:
                node.children[patch_sha1] = _Node(commit)
            node = node.children[patch_sha1]

    def save(self, path=None):
        """
        Write cache data back to the file system.

        By default, the same path passed to the constructor is used. The
        parameter ``path`` can be used to provide an alternative destination.
        """
        self.__cache_data.save(pathlib.Path(path or self.__path))


_logger = logging.getLogger(__name__)


class _Node:
    """
    The class ``_Node`` is used to represent a node in a cache tree.

    The objective of a cache tree is to match patch files with commit objects in
    the git repository.

    A path in such a tree represents a (possibly partial) pile revision. Such a
    path can be represented as ``[b, p[0], p[p_len - 1]]``, with:

      - ``b`` as the node representing the baseline for the pile;
      - ``p[i]`` as the node representing the ``i``-th patch of the pile;
      - ``p_len + 1`` as the length of the path. The path may be partially
        representing the pile revision when ``p_len`` is less than the number of
        patches in the pile.

    Note that the root node is omitted from such a representation as it is not
    relevant to the discussion.

    Paths for two different pile revisions will share the first ``k > 1`` nodes
    if they have identical baselines and have the same first ``k - 1`` patches
    in their series.

    Except for the root of the tree, each node stores the sha-1 identifier for a
    commit object in the ``commit`` attribute. For baseline nodes, ``b.commit``
    refers to the commit object of the baseline; for patch nodes, ``p[i]``
    refers to the commit object created by applying the respective patch after
    applying all ``p[:i]`` patches in sequence on top of the baseline.

    As such, the cache tree can be used to avoid recreating commit objects in a
    genbranch operation. Given a path, the latest node with an existing commit
    object can be searched and used as base for applying the remaining patches.

    In order to allow building the path for a pile revision, each node has a
    ``children`` attribute as a ``dict`` mapping the sha-1 hash of each child's
    patch file to the child node object.
    """

    def __init__(self, commit):
        self.children = {}
        self.commit = commit


class _CacheData:
    SCHEMA_VERSION = 2

    def __init__(self):
        self.trees = {}

    @classmethod
    def load(cls, path):
        try:
            with open(path, "rb") as f:
                schema_version, data_bytes = pickle.load(f)

            if schema_version == cls.SCHEMA_VERSION:
                return pickle.loads(data_bytes)
            else:
                _logger.info(f"creating new cache structure because {path} uses a different schema version.")
        except FileNotFoundError:
            _logger.info(f"creating new cache structure because {path} does not exist yet.")
        except Exception as e:
            _logger.info(f"creating new cache structure because of unknown error loading {path}.")
            _logger.warning(f"failed to load genbranch cache: {e}")
            _logger.warning("using a fresh new cache")

        return _CacheData()

    def save(self, path):
        data_bytes = pickle.dumps(self)
        # Using dir=output_path.parent to ensure files will be in the same file
        # system for the atomic replace operation.
        f = tempfile.NamedTemporaryFile(delete=False, dir=path.parent)
        try:
            pickle.dump((self.SCHEMA_VERSION, data_bytes), f)
        except Exception:  # pragma: no cover
            f.close()
            pathlib.Path(f.name).unlink()
            raise
        else:
            f.close()
            pathlib.Path(f.name).replace(path)

    # We need to implement ``__getstate__()`` and ``__setstate__()`` because
    # pickle does not cope well with highly nested structures, which would be
    # the case for a long patch series.
    def __getstate__(self):
        state = dict(self.__dict__)
        state["trees"] = {k: self.__flatten_tree(root) for k, root in state["trees"].items()}
        return state

    def __setstate__(self, state):
        state["trees"] = {k: self.__unflatten_tree(flat_data) for k, flat_data in state["trees"].items()}
        self.__dict__.update(state)

    def __flatten_tree(self, root):
        stack = collections.deque([[root, list(root.children), -1]])
        flat_data = []
        while stack:
            node, children_keys, child_idx = stack[-1]
            if child_idx == -1:
                node_dict = dict(node.__dict__)
                node_dict.pop("children")
                flat_data.append(("node-start", node_dict))
                stack[-1][-1] += 1
            elif child_idx < len(children_keys):
                child_key = children_keys[child_idx]
                child = node.children[child_key]
                flat_data.append(("node-child", child_key))
                stack[-1][-1] += 1
                stack.append([child, list(child.children), -1])
            else:
                flat_data.append(("node-end", None))
                stack.pop()
        return flat_data

    def __unflatten_tree(self, flat_data):
        _, node_dict = flat_data[0]
        root = _Node.__new__(_Node)
        root.__dict__.update(node_dict)
        root.children = {}
        stack = collections.deque([root])
        for entry_type, entry_data in flat_data[1:]:
            if entry_type == "node-start":
                child_key = stack.pop()
                node_dict = entry_data
                node = _Node.__new__(_Node)
                node.__dict__.update(node_dict)
                node.children = {}
                stack[-1].children[child_key] = node
                stack.append(node)
            elif entry_type == "node-child":
                key = entry_data
                stack.append(key)
            elif entry_type == "node-end":
                stack.pop()
            else:
                raise Exception(f"unexpected entry type: {entry_type}")  # pragma: no cover
        return root
