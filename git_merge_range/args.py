# SPDX-License-Identifier: LGPL-2.1+
from __future__ import annotations

import argparse
import subprocess
import typing as ty

from . import gitutil


class Args(ty.NamedTuple):
    current: gitutil.NormalizedRevRange
    base: gitutil.NormalizedRevRange
    other: gitutil.NormalizedRevRange
    target: ty.Optional[str]
    onto: ty.Optional[str]
    todo_append: ty.List[str] = []


parser = argparse.ArgumentParser(
    description="""
git-merge-range implements a 3-way-ish merge of commit ranges.

The arguments current, base and other have similar semantics for those of
git-merge-file: changes from the base to the other range are incorporated into
the current range.

This is implemented by a "diff-wise" matching of commits from the three ranges
(currently using git-range-diff) and merging the commit sequences into a
rebase-todo that is fed to an interactive rebase for editing.

Conflicts are presented in the rebase-todo with the usual conflict markers.
Conflicts usually arise when both current and other ranges change common
subranges of base with non-matching commits.

Each "current", "base" and "other" argument can be either a revision range or a
single revision. In the case of the latter, the single revision is taken as the
head and the merge base (git merge-base --octopus ...) of the three ranges'
heads is used as default base.
""",
)
parser.add_argument(
    "current",
    nargs="?",
    help="""
    Revision or revision range to be used as "current". If omitted, the
    currently checked out branch is used.
    """,
)
parser.add_argument(
    "base",
    help="""
    Revision or revision range to be used as "base".
    """,
)
parser.add_argument(
    "other",
    help="""
    Revision or revision range to be used as "other".
    """,
)
parser.add_argument(
    "--target",
    "-b",
    help="""
    Name of the branch to be created/updated to point to the head of the
    resulting range after the rebase is successful. If this is omitted, then the
    user is left with a detached head.
    """,
)
parser.add_argument(
    "--onto",
    help="""
    By default, the rebase is done on top of the base revision of the current
    range. A different base can be passed with this option.
    """,
)
parser.add_argument(
    "--todo-append",
    action="append",
    help="""
    Append the argument as a new line in the rebase todo. This can be useful for
    other tools that want to perform extra commands as part of the rebase. This
    option can be passed multiple times. (Note that the GIT_SEQUENCE_EDITOR is
    also honored, in case more complex edition is needed.)
    """,
)


def parse_argv(argv: ty.List[str]) -> Args:
    git = gitutil.Git()
    args = parser.parse_args(argv)

    if args.current is None:
        args.current = git("branch", "--show-current")
        if not args.current:
            raise parser.error('not currently checked out on any branch, please pass the "current" argument explicitly')

    norm_current, norm_base, norm_other = normalize_ranges(args.current, args.base, args.other)

    return Args(
        current=norm_current,
        base=norm_base,
        other=norm_other,
        target=args.target,
        onto=args.onto,
        todo_append=args.todo_append,
    )


def normalize_ranges(
    current: str, base: str, other: str
) -> ty.Tuple[gitutil.NormalizedRevRange, gitutil.NormalizedRevRange, gitutil.NormalizedRevRange]:
    git = gitutil.Git()
    heads = ["", "", ""]
    bases = ["", "", ""]
    default_head = ""

    argnames = "current", "base", "other"
    argvalues = current, base, other
    for i, (argname, rangestr) in enumerate(zip(argnames, argvalues)):
        try:
            if git("rev-parse", "--no-revs", rangestr):
                raise parser.error(f"invalid range value for {argname}: {rangestr}")
            revs = git("rev-parse", "--revs-only", rangestr).split()
        except subprocess.CalledProcessError as e:
            raise parser.error(f"invalid range value for {argname}: {rangestr}\nerror message from git-rev-parse:\n{e.stderr}")

        if len(revs) == 1:
            if revs[0].startswith("^"):
                if default_head == "":
                    default_head = git("rev-parse", "HEAD")
                bases[i], heads[i] = revs[0][1:], default_head
            else:
                bases[i], heads[i] = "", revs[0]
        elif len(revs) == 2:
            if revs[0].startswith("^") and revs[1].startswith("^"):
                raise parser.error(f"invalid range value for {argname}: {rangestr}, which resolves to {revs}")

            if revs[0].startswith("^"):
                bases[i], heads[i] = revs[0][1:], revs[1]
            else:
                bases[i], heads[i] = revs[1][1:], revs[0]
        else:
            raise parser.error(
                f"invalid range value for {argname}: {rangestr}, which resolves to more than two revisions: {revs}"
            )

    if any(b == "" for b in bases):
        default_base = git("merge-base", "--octopus", *heads)
        bases = [default_base if b == "" else b for b in bases]

    return (
        gitutil.NormalizedRevRange(bases[0], heads[0]),
        gitutil.NormalizedRevRange(bases[1], heads[1]),
        gitutil.NormalizedRevRange(bases[2], heads[2]),
    )
