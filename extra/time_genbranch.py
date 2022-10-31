#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1+
"""
Run genbranch for the last N (given by -n) pile commits and generate a timing
report. This runs genbranch in both uncached and cached modes and reports
average timings as well as speedup information for cached operations.
"""
import argparse
import os
import os.path
import statistics
import subprocess
import sys
import tempfile
import time


def gitp(*args, **kw):
    cmd = ("git", *args)
    kw.setdefault("check", True)
    kw.setdefault("text", True)
    kw.setdefault("stdout", subprocess.PIPE)
    return subprocess.run(cmd, **kw)


def git(*args, **kw):
    return gitp(*args, **kw).stdout.strip()


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description=__doc__,
    )
    parser.add_argument(
        "-n",
        type=int,
        required=True,
        help="""Number of pile commits to use.""",
    )
    parser.add_argument(
        "--no-uncached",
        action="store_false",
        dest="uncached",
        help="""Do not run uncached genbranch.""",
    )
    parser.add_argument(
        "--no-cached",
        action="store_false",
        dest="cached",
        help="""Do not run cached genbranch.""",
    )

    args = parser.parse_args(argv)

    if args.n <= 0:
        parser.error("argument to -n must be a non-zero positive integer")

    if not args.uncached and not args.cached:
        parser.error("at least one mode (cached or uncached) must be enabled")

    return args


def info(*k, **kw):
    kw["file"] = sys.stderr
    kw["flush"] = True
    print(*k, **kw)


def status(msg, **kw):
    kw["end"] = ""
    info(f"\r\033[K{msg}", **kw)


def run_genbranch_operations(repo_info, num_pile_commits, cached):
    if cached:
        cache_file = tempfile.NamedTemporaryFile(delete=False, dir=repo_info["git_dir"])
        cache_file.close()

    genbranch_cmd = ("pile", "genbranch", "-i")
    if cached:
        genbranch_cmd = ("-c", f"pile.genbranch-cache-path={os.path.basename(cache_file.name)}", *genbranch_cmd, "--cache")
        status_prefix = "Running cached genbranch"
    else:
        genbranch_cmd += ("--no-cache",)
        status_prefix = "Running uncached genbranch"

    timings = []
    cur_avg = 0
    cur_std = 0
    try:
        git("checkout", "--detach", "-q")

        # Define a common starting point. Note that this also initializes the
        # cache for cached mode.
        info(f"Running genbranch for {repo_info['pile_branch']}~{num_pile_commits} to initialize")
        git("-C", repo_info["patches_dir"], "checkout", "-q", "-f", "--detach", f"{repo_info['pile_branch']}~{num_pile_commits}")
        gitp(*genbranch_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        for i in reversed(range(num_pile_commits)):
            git("-C", repo_info["patches_dir"], "checkout", "-q", "-f", "--detach", f"{repo_info['pile_branch']}~{i}")
            status(f"{status_prefix} [{num_pile_commits - i}/{num_pile_commits}] (cur_avg={cur_avg:.3f}±{cur_std:.3f})")
            t0 = time.monotonic()
            gitp(*genbranch_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            dt = time.monotonic() - t0
            timings.append(dt)
            cur_avg = statistics.mean(timings) if len(timings) > 0 else 0
            cur_std = statistics.stdev(timings) if len(timings) > 1 else 0
            status(f"{status_prefix} [{num_pile_commits - i}/{num_pile_commits}] (cur_avg={cur_avg:.3f}±{cur_std:.3f})")
        info()
    finally:
        if cached:
            os.unlink(cache_file.name)
    return timings


def print_report(uncached_timings, cached_timings):
    avg_data = []

    if uncached_timings:
        print("Uncached timings:", " ".join(f"{dt:.3f}" for dt in uncached_timings))
        avg_data.append(
            (
                "Uncached average timing",
                statistics.mean(uncached_timings),
                statistics.stdev(uncached_timings) if len(uncached_timings) > 1 else 0,
            )
        )

    if cached_timings:
        print("Cached timings:", " ".join(f"{dt:.3f}" for dt in cached_timings))
        avg_data.append(
            (
                "Cached average timing",
                statistics.mean(cached_timings),
                statistics.stdev(cached_timings) if len(cached_timings) > 1 else 0,
            )
        )

    speedups = None
    if uncached_timings and cached_timings:
        speedups = [uncached_dt / cached_dt for uncached_dt, cached_dt in zip(uncached_timings, cached_timings)]
        avg_data.append(
            (
                "Average speedup",
                statistics.mean(speedups),
                statistics.stdev(speedups),
            )
        )

    print()
    print("Number of pile commits:", len(uncached_timings or cached_timings))
    for title, avg, std in avg_data:
        print(f"{title}: {avg:.3f}±{std:.3f}")

    if speedups:
        print()
        print("Cumulative histogram of minimal speedup:")
        sorted_speedups = sorted(speedups, reverse=True)
        histogram_data = [(0, sorted_speedups[0])]
        histogram_data.extend((p, sorted_speedups[int(p / 100 * len(sorted_speedups)) - 1]) for p in (25, 50, 75, 100))
        histogram_data = [(f"{pct}%", f"{s:.1f}") for pct, s in histogram_data]
        speedup_width = max(len("Min Speedup"), *(len(row[1]) for row in histogram_data))
        print("====", "=" * speedup_width)
        print(" Pct", f"{'Min Speedup':>{speedup_width}}")
        print("----", "-" * speedup_width)
        for pct, speedup in histogram_data:
            print(f"{pct:>4}", f"{speedup:>{speedup_width}}")
        print("====", "=" * speedup_width)


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    args = parse_args(argv)

    repo_info = {
        "toplevel": git("rev-parse", "--show-toplevel"),
        "git_dir": git("rev-parse", "--git-dir"),
        "patches_dir": git("config", "pile.dir"),
        "pile_branch": git("config", "pile.pile-branch"),
    }

    os.chdir(repo_info["toplevel"])

    saved_rev = git("branch", "--show-current") or git("rev-parse", "HEAD")
    saved_pile_rev = git("-C", repo_info["patches_dir"], "branch", "--show-current") or git(
        "-C", repo_info["patches_dir"], "rev-parse", "HEAD"
    )

    uncached_timings, cached_timings = None, None
    try:
        if args.uncached:
            uncached_timings = run_genbranch_operations(repo_info, num_pile_commits=args.n, cached=False)

        if args.cached:
            cached_timings = run_genbranch_operations(repo_info, num_pile_commits=args.n, cached=True)
    finally:
        git("reset", "-q", "--hard")
        git("checkout", "-q", "-f", saved_rev)
        git("-C", repo_info["patches_dir"], "checkout", "-q", "-f", saved_pile_rev)

    print_report(uncached_timings, cached_timings)


if __name__ == "__main__":
    main()
