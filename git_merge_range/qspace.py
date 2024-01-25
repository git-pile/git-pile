# SPDX-License-Identifier: LGPL-2.1+
"""
This module provides a very simple interface for constructing a set of
equivalence classes (a.k.a. quotient space or set).

The set is constructed by feeding the builder with subsets of equivalence
classes. Each call to ``update()`` tells the builder that the items passed in
belong to the same equivalence class::

    >>> builder = QuotientSpaceBuilder()

    >>> builder.update("dog", "cat")

    >>> builder.update("apple")  # A single item can also be added

    >>> builder.update("banana", "apple")

    >>> builder.update("banana", "watermelon", "orange")

    >>> builder.update("cat", "lion", "mouse")

    >>> builder.update("mouse")

    >>> builder.update("lemon", "grape")

When all items are added the set can be created with the ``build()`` method,
which returns a ``QuotientSpace`` object::

    >>> qs = builder.build()

The identity of the equivalence set for an item can be checked with
``qs.index()``::

    >>> qs.index("dog") == qs.index("cat") == qs.index("lion") == qs.index("mouse")
    True

    >>> qs.index("apple") == qs.index("banana") == qs.index("watermelon") == qs.index("orange")
    True

    >>> qs.index("lemon") == qs.index("grape")
    True

    >>> qs.index("dog") == qs.index("apple")
    False

    >>> qs.index("apple") == qs.index("lemon")
    False

The list of sets can be generated with ``qs.generate_sets()``::

    >>> s = qs.generate_sets()

    >>> len(s)
    3

    >>> sorted(s[qs.index("apple")])
    ['apple', 'banana', 'orange', 'watermelon']

    >>> sorted(s[qs.index("lion")])
    ['cat', 'dog', 'lion', 'mouse']

    >>> sorted(s[qs.index("grape")])
    ['grape', 'lemon']
"""
from __future__ import annotations

import collections
import itertools
import typing as ty


T = ty.TypeVar("T")


class QuotientSpaceBuilder(ty.Generic[T]):
    def __init__(self) -> None:
        self.__graph: ty.Dict[T, ty.List[T]] = {}

    def update(self, *items: T) -> None:
        self.__add_cycle(items)

    def __add_cycle(self, items: ty.Tuple[T, ...]) -> None:
        for a, b in itertools.pairwise(items + (items[0],)):
            if a not in self.__graph:
                self.__graph[a] = []
            self.__graph[a].append(b)

    def build(self) -> QuotientSpace[T]:
        cur_idx = 0
        idx_map = {}

        for item in self.__graph:
            if item in idx_map:
                continue
            # Do a walk in the connected component
            q = collections.deque([item])
            while q:
                item = q.pop()
                idx_map[item] = cur_idx
                if item in self.__graph:
                    for child in self.__graph[item]:
                        if child in idx_map:
                            continue
                        q.append(child)
            cur_idx += 1

        return QuotientSpace(idx_map)


class QuotientSpace(ty.Generic[T]):
    def __init__(self, idx_map: ty.Dict[T, int]) -> None:
        self.__idx_map = idx_map

    def index(self, item: T) -> int:
        return self.__idx_map[item]

    def generate_sets(self) -> ty.List[ty.Set[T]]:
        max_idx = max(self.__idx_map.values())
        ret = [ty.cast(ty.Set[T], set()) for _ in range(max_idx + 1)]
        for item, idx in self.__idx_map.items():
            ret[idx].add(item)
        return ret
