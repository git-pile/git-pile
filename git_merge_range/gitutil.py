# SPDX-License-Identifier: LGPL-2.1+
from __future__ import annotations

import subprocess
import re
import typing as ty


class Git:
    def __call__(self, *args: str, strip: ty.Union[bool, str] = True, **subprocess_kw: ty.Any) -> str:
        subprocess_kw["capture_output"] = True
        subprocess_kw["text"] = True

        proc = self.proc(*args, **subprocess_kw)

        if strip is False:
            return proc.stdout
        elif strip is True:
            return proc.stdout.strip()
        else:
            return proc.stdout.strip(strip)

    def proc(self, *args: str, **subprocess_kw: ty.Any) -> subprocess.CompletedProcess[str]:
        subprocess_kw.setdefault("check", True)
        return subprocess.run(("git", *args), **subprocess_kw)

    def commit_list(self, revrange: RevRange) -> ty.List[ShortCommitInfo]:
        cmd = "log", "--format=%h %s", "--reverse", str(revrange)
        return [
            ShortCommitInfo(sha1, subject)
            for sha1, subject in (line.split(maxsplit=1) for line in self(*cmd, strip=False).splitlines())
        ]

    def range_diff(self, range_a: RevRange, range_b: RevRange) -> ty.List[RangeDiffEntry]:
        line_re = re.compile(r" *(-|\d+): *([0-9a-f]+|-+) *([<>=!]) *(-|\d+): *([0-9a-f]+|-+) .*")
        cmd = "range-diff", "-s", str(range_a), str(range_b)
        ret = []
        for line in self(*cmd, strip=False).splitlines():
            m = line_re.match(line)
            if m is None:
                raise Exception(f"unable to parse range-diff line: {line!r}")

            left, status, right = m.group(2, 3, 5)

            if left[0] == "-":
                left = ""

            if right[0] == "-":
                right = ""

            ret.append(RangeDiffEntry(left, right, status))
        return ret


class ShortCommitInfo(ty.NamedTuple):
    sha1: str
    subject: str


class NormalizedRevRange(ty.NamedTuple):
    base: str
    head: str

    def __str__(self) -> str:
        return f"{self.base}..{self.head}"


RevRange = ty.Union[str, NormalizedRevRange]


class RangeDiffEntry(ty.NamedTuple):
    left: str
    right: str
    status: str
