# SPDX-License-Identifier: LGPL-2.1+
from __future__ import annotations

import sys
import traceback
import typing as ty

import git_merge_range


def main() -> ty.NoReturn:
    exit_code: ty.Union[int, str, None] = 0
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--rebase-seq-editor":
            generated_todo_path = sys.argv[2]
            original_todo_path = sys.argv[3]
            git_merge_range.run_rebase_seq_editor(generated_todo_path, original_todo_path)
        else:
            try:
                args = git_merge_range.parse_argv(sys.argv[1:])
            except SystemExit as e:
                exit_code = e.code
            else:
                git_merge_range.run(args)
    except git_merge_range.RunError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    except:
        print("unexpected error! This is probably a BUG. See traceback below:")
        traceback.print_exc()
        sys.exit(1)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
