# SPDX-License-Identifier: LGPL-2.1+
from __future__ import annotations

import collections
import os
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

    def commit_list(self, revrange: RevRange) -> ty.List[CommitData]:
        ret = []
        # TODO: We might want to let user decided what to use for metadata
        metadata_fmt = "%an%n%ae%n%B"
        cmd = "log", "-z", "--patch", f"--format=%x00%h%x00%s%x00{metadata_fmt}", "--reverse", str(revrange)
        out = self(*cmd, strip=False)
        data = out.split("\x00")[1:]
        for i in range(0, len(data), 4):
            sha1, subject, metadata, diff = data[i : i + 4]
            filtered_diff = self.__diff_hunk_lines_re.sub("@@ @@", diff)
            filtered_diff = self.__diff_ignore_headers_re.sub("", filtered_diff)
            ret.append(CommitData(sha1, subject, metadata, filtered_diff))
        return ret

    def find_matching_commits(
        self, commits_a: ty.List[CommitData], commits_b: ty.List[CommitData]
    ) -> ty.Generator[ty.Tuple[CommitData, CommitData], None, None]:
        # No need to compare full message body and diff content if the subjects
        # do not match. Let's use this map for that, which should make the
        # expected complexity linear.
        subject_to_b: ty.DefaultDict[str, ty.List[CommitData]] = collections.defaultdict(list)
        for b in commits_b:
            subject_to_b[b.subject].append(b)

        for a in commits_a:
            if a.subject not in subject_to_b:
                continue
            for b in subject_to_b[a.subject]:
                if a.sha1 != b.sha1:
                    if a.metadata != b.metadata:
                        continue
                    if a.filtered_diff != b.filtered_diff:
                        continue
                yield a, b

    def sequence_editor(self):
        try:
            return self("var", "GIT_SEQUENCE_EDITOR")
        except subprocess.CalledProcessError:
            # Support for GIT_SEQUENCE_EDITOR in git-var was added only in git
            # v2.40. Let's fallback to mimic git's implementation.
            editor = os.environ.get("GIT_SEQUENCE_EDITOR")

            if not editor:
                editor = self("config", "get", "sequence.editor")

            if not editor:
                editor = self("var", "GIT_EDITOR")

            return editor

    __diff_hunk_lines_re = re.compile(r"^@@ -\d+,\d+ \+\d+,\d+ @@", re.M)
    __diff_ignore_headers_re = re.compile(r"^(index|similarity|dissimilarity) .*$\n", re.M)


class CommitData(ty.NamedTuple):
    sha1: str
    subject: str
    metadata: str
    filtered_diff: str


class NormalizedRevRange(ty.NamedTuple):
    base: str
    head: str

    def __str__(self) -> str:
        return f"{self.base}..{self.head}"


RevRange = ty.Union[str, NormalizedRevRange]
