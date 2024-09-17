# SPDX-License-Identifier: LGPL-2.1+
from __future__ import annotations

import itertools
import os
import sys
import tempfile
import typing as ty

from . import args as argsmod
from . import errors
from . import gitutil
from . import qspace


class Run:
    def __init__(self, args: argsmod.Args) -> None:
        self.__args = args
        self.__git = gitutil.Git()

    def run(self) -> None:
        self.__get_commits()
        self.__build_qspace()
        self.__merge_indices()
        self.__generate_rebase_todo()
        self.__exec_rebase()

    def __get_commits(self) -> None:
        self.__current_commits = self.__git.commit_list(self.__args.current)
        self.__base_commits = self.__git.commit_list(self.__args.base)
        self.__other_commits = self.__git.commit_list(self.__args.other)
        self.__commit_map = {
            c.sha1: c
            for c in itertools.chain(
                self.__current_commits,
                self.__base_commits,
                self.__other_commits,
            )
        }

    def __build_qspace(self) -> None:
        qs_builder = qspace.QuotientSpaceBuilder[str]()

        for a, b in self.__git.find_matching_commits(self.__base_commits, self.__current_commits):
            qs_builder.update(a.sha1, b.sha1)

        for a, b in self.__git.find_matching_commits(self.__base_commits, self.__other_commits):
            qs_builder.update(a.sha1, b.sha1)

        for a, b in self.__git.find_matching_commits(self.__current_commits, self.__other_commits):
            qs_builder.update(a.sha1, b.sha1)

        for c in self.__commit_map:
            qs_builder.update(c)

        self.__qs = qs_builder.build()

    def __merge_indices(self) -> None:
        current_indices = [self.__qs.index(c.sha1) for c in self.__current_commits]
        base_indices = [self.__qs.index(c.sha1) for c in self.__base_commits]
        other_indices = [self.__qs.index(c.sha1) for c in self.__other_commits]

        temp_files = []
        try:
            for index_list in (current_indices, base_indices, other_indices):
                lines = [str(i) for i in index_list]
                f = tempfile.NamedTemporaryFile(mode="w", delete=False)
                temp_files.append(f)
                print("\n".join(lines), file=f)
                f.close()

            cmd = (
                "merge-file",
                "-q",
                "-p",
                "--diff3",
                "--marker-size=7",
                "-L",
                "CURRENT",
                "-L",
                "BASE",
                "-L",
                "OTHER",
                temp_files[0].name,
                temp_files[1].name,
                temp_files[2].name,
            )
            p = self.__git.proc(*cmd, check=False, text=True, capture_output=True)
            if 0 <= p.returncode <= 127:
                result_lines = p.stdout.splitlines()
            else:
                raise errors.RunError(f"failed to call git merge-file (exit code: {p.returncode}):\n{p.stderr}")
        finally:
            for f in temp_files:
                try:
                    os.unlink(f.name)
                except:
                    pass

        chunks = [("merged", ty.cast(ty.List[int], []))]
        for line in result_lines:
            state = chunks[-1][0]
            if state == "merged":
                if line == "<<<<<<< CURRENT":
                    chunks.append(("ours", []))
                else:
                    chunks[-1][1].append(int(line))
            elif state == "ours":
                if line == "||||||| BASE":
                    chunks.append(("base", []))
                else:
                    chunks[-1][1].append(int(line))
            elif state == "base":
                if line == "=======":
                    chunks.append(("theirs", []))
                else:
                    chunks[-1][1].append(int(line))
            elif state == "theirs":
                if line == ">>>>>>> OTHER":
                    chunks.append(("merged", []))
                else:
                    chunks[-1][1].append(int(line))
            else:
                raise Exception(f"unhandled state {state} - this is a bug")

        self.__chunks = chunks

    def __generate_rebase_todo(self) -> None:
        todo_lines = []
        qs_sets = self.__qs.generate_sets()

        current_sha1_set = set(c.sha1 for c in self.__current_commits)
        base_sha1_set = set(c.sha1 for c in self.__base_commits)
        other_sha1_set = set(c.sha1 for c in self.__other_commits)

        for chunk_type, indices in self.__chunks:
            indent = "    "
            if chunk_type == "merged":
                marker = ""
                indent = ""
                sha1_set = current_sha1_set
            elif chunk_type == "ours":
                marker = "<<<<<<< OURS"
                sha1_set = current_sha1_set
            elif chunk_type == "base":
                marker = "||||||| BASE"
                sha1_set = base_sha1_set
            elif chunk_type == "theirs":
                marker = "======="
                sha1_set = other_sha1_set
            else:
                raise Exception(f"bug: unhandled {chunk_type}")

            if marker:
                todo_lines.append(marker)

            for idx in indices:
                commit_data: ty.Optional[gitutil.CommitData] = None
                if chunk_type == "merged":
                    sha1_set = current_sha1_set
                    for sha1 in qs_sets[idx]:
                        if sha1 in sha1_set:
                            commit_data = self.__commit_map[sha1]
                            break
                    else:
                        sha1_set = other_sha1_set

                if commit_data is None:
                    for sha1 in qs_sets[idx]:
                        if sha1 in sha1_set:
                            commit_data = self.__commit_map[sha1]
                            break
                    else:
                        raise Exception("bug: sha1 not found for index")

                if sha1_set is current_sha1_set:
                    origin = "OURS"
                elif sha1_set is base_sha1_set:
                    origin = "BASE"
                elif sha1_set is other_sha1_set:
                    origin = "THEIRS"
                else:
                    raise Exception("bug: unhandled sha1_set")

                if len(qs_sets[idx]) == 1:
                    extra_matches_str = ""
                elif chunk_type != "merged":
                    extra_matches_str = ""
                    current_matches = [sha1 for sha1 in qs_sets[idx] if sha1 in current_sha1_set and sha1 != commit_data.sha1]
                    base_matches = [sha1 for sha1 in qs_sets[idx] if sha1 in base_sha1_set and sha1 != commit_data.sha1]
                    other_matches = [sha1 for sha1 in qs_sets[idx] if sha1 in other_sha1_set and sha1 != commit_data.sha1]

                    if current_matches:
                        extra_matches_str += f" == OURS({','.join(current_matches)})"

                    if other_matches:
                        extra_matches_str += f" == THEIRS({','.join(other_matches)})"

                    if base_matches:
                        extra_matches_str += f" == BASE({','.join(base_matches)})"

                if chunk_type != "merged" or len(qs_sets[idx]) == 1:
                    todo_lines.append(f"{indent}# INFO: {origin}{extra_matches_str}")

                todo_lines.append(f"{indent}pick {commit_data.sha1} {commit_data.subject}")

            if chunk_type == "theirs":
                todo_lines.append(">>>>>>> THEIRS")

        if self.__args.todo_append:
            todo_lines.append("# Extra commands passed via --todo-append")
            for line in self.__args.todo_append:
                todo_lines.append(line)

        if self.__args.target:
            todo_lines.append("# Final command to create/update the target branch")
            todo_lines.append(f"exec git checkout -B '{self.__args.target}' HEAD")

        self.__rebase_todo = "\n".join(todo_lines) + "\n"

    def __exec_rebase(self) -> ty.NoReturn:
        current_head_hash = self.__git("rev-parse", self.__args.current.head)

        f = tempfile.NamedTemporaryFile(mode="w", delete=False)
        try:
            f.write(self.__rebase_todo)
            f.close()

            entrypoint = sys.argv[0]  # FIXME: Receive this as argument.
            env = dict(os.environ)
            original_seq_editor = self.__git.sequence_editor()
            env["GIT_SEQUENCE_EDITOR"] = f'"{entrypoint}" --rebase-seq-editor "{f.name}"'
            if original_seq_editor:
                # This should either launch the user editor or any other stuff
                # that is configured as sequence editor.
                env["GIT_SEQUENCE_EDITOR"] += f' "$1" && {original_seq_editor}'

            cmd: ty.Tuple[str, ...] = (
                "git",
                "-c",
                "rebase.missingCommitsCheck=ignore",
                "rebase",
                "-i",
                self.__args.current.base,
                current_head_hash,
            )
            if self.__args.onto is not None:
                cmd += ("--onto", self.__args.onto)

            os.execvpe("git", cmd, env)
        finally:
            try:
                os.unlink(f.name)
            except:
                pass
            raise


def run(args: argsmod.Args) -> None:
    Run(args).run()
