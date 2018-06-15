#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1+

import argparse
import mailbox
import os
import os.path
import re
import sys

try:
    import argcomplete
except ImportError:
    pass

args = None
subject_regex_str = r"\[PATCH *(?P<project>[\w-]*)? *(?P<version>v[0-9]*)? *(?P<number>[0-9]+/[0-9]*)? *\] (?P<title>.*)$"
subject_regex = re.compile(subject_regex_str, re.MULTILINE)


class Patch:
    def __init__(self, msg, match):
        self.msg = msg

        number = match.group("number")
        if number:
            self.number, self.total = (int(x) for x in number.strip().split('/'))
        else:
            self.number = 1
            self.total = 1

        self.project = match.group("project")
        self.version = match.group("version")
        self.title = match.group("title").strip()

        # transliterate
        self.filename = self.title.translate({
            ord(" "): "-", ord(":"): "-", ord("/"): "-", ord("*"): "-",
            ord("("): "-", ord(")"): "-",
        })
        # remove duplicates and dash in the end
        self.filename = re.sub(r"--+", r"-", self.filename)
        self.filename = self.filename.strip('-')

        self.filename = self.filename + '.patch'

    def __str__(self):
        return self.title

    def parse(msg):
        match = subject_regex.search(msg["subject"])
        if match:
            return Patch(msg, match)
        for alt in args.allow_prefixes:
            alt_subject_str = subject_regex_str.replace("PATCH", alt)
            match = re.search(alt_subject_str, msg["subject"], re.MULTILINE)
            if match:
                return Patch(msg, match)

        return None


def parse_args():
    global args

    parser = argparse.ArgumentParser(
        description="Prepare a mbox for use by git - improved version over GIT-MAILSPLIT(1)")

    parser.add_argument(
        "-o", "--output", help="Directory in which to place final patches",
        metavar="DIR",
        default=".")
    parser.add_argument(
        "-p", "--allow-prefixes", help="Besides \"PATCH\" as prefix, allow any of the PREFIX to appear in the subject",
        nargs='+',
        metavar="PREFIX",
        default=[])

    group = parser.add_argument_group("Required arguments")
    group.add_argument("mbox", help="mbox file to process", metavar="MBOX_FILE")

    try:
        argcomplete.autocomplete(parser)
    except NameError:
        pass
    args = parser.parse_args()


def main():
    parse_args()

    box = mailbox.mbox(args.mbox)
    if box is None or len(box) == 0:
        print("No emails in mailbox '%s'?" % args.mbox)
        return 1

    patches = []
    for msg in box:
        p = Patch.parse(msg)
        if not p:
            print("Could not parse subject '%s'" % msg["subject"], file=sys.stderr)
            return 1
        patches.append(p)

    # sanity checks
    # 1) Total, if exists, is the same on all patches
    total = patches[0].total
    coverletter = None
    for p in patches[1:]:
        if p.total != total:
            print("Patch '%s' has a different total %d" % (p.title, p.total), file=sys.stderr)
            return 1

    # 2) Only one coverletter
    for p in patches:
        if p.number == 0:
            if coverletter:
                print("Patch '%s' and '%s' are coverletters" %
                      p.title, coverletter.title, file=sys.stderr)
                return 1
            coverletter = p

    # 3) total == len(mbox) or total == len(mbox) - 1 when we have a coverletter
    if total is not None:
        x = total
        if coverletter:
            x = x + 1
        if len(box) != x:
            print("Number of patches don't match total: %d vs %d" % (len(box), x), file=sys.stderr)
            return 1

    if (len(patches) == 1):
        patches_sorted = patches
    else:
        patches_sorted = sorted(patches, key=lambda p: p.number)

    os.makedirs(args.output, exist_ok=True)

    idx = 1
    for p in patches_sorted:
        if p == coverletter:
            continue
        fn = "%04d-%s" % (idx, p.filename)
        fn = os.path.join(args.output, fn)
        with open(fn, "w") as f:
            f.write(p.msg.get_payload())
        print(fn)
        idx += 1
