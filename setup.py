#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1+

from os import path as op
from setuptools import setup
from git_pile import __version__

import pathlib
import os
import sys

HERE = pathlib.Path(__file__).parent
README = (HERE / "README.md").read_text()

if sys.version_info < (3, 7):
    sys.exit("Sorry, we need at least Python 3.7.x")

# installing to user dir or inside virtualenv
if ("install" in sys.argv and "--user" in sys.argv) or sys.base_prefix != sys.prefix:
    # this is not a standard location, the user still needs to source the file,
    # but at least it's installed somewhere we can document
    datadir = os.environ.get("XDG_DATA_HOME", op.join(op.expanduser("~"), ".local", "share"))
    bash_completion_dir = op.join(datadir, "git-pile", "bash_completion")
    mandir = op.join(datadir, "man")
else:
    mandir = "/usr/share/man"
    bash_completion_dir = "/etc/bash_completion.d"

if "BASH_COMPLETION_DIR" in os.environ:
    bash_completion_dir = os.environ["BASH_COMPLETION_DIR"]

setup(
    name="git-pile",
    zip_safe=False,
    version=__version__,
    description="Manage a pile of patches on top of git branches",
    long_description=README,
    long_description_content_type="text/markdown",
    url="https://github.com/git-pile/git-pile",
    maintainer="git-pile contributors",
    include_package_data=True,
    maintainer_email="lucas.demarchi@intel.com",
    license="LGPLv2+",
    scripts=["git-pile"],
    classifiers=[
        "Intended Audience :: Developers",
        "License :: OSI Approved",
        "Programming Language :: Python",
        "Topic :: Software Development",
        "Operating System :: POSIX",
        "Operating System :: Unix",
    ],
    packages=["git_pile"],
    package_data={
        "git_pile": [
            op.join("data", "git-cover-order.txt"),
        ]
    },
    python_requires=">=3.6",
    extras_require={
        "tests": ["coverage~=6.5"],
    },
    data_files=[
        (bash_completion_dir, ["extra/git-pile-complete.sh"]),
        (
            op.join(mandir, "man1"),
            [
                "man/man1/git-pile-am.1",
                "man/man1/git-pile-baseline.1",
                "man/man1/git-pile-destroy.1",
                "man/man1/git-pile-format-patch.1",
                "man/man1/git-pile-genbranch.1",
                "man/man1/git-pile-genpatches.1",
                "man/man1/git-pile-setup.1",
                "man/man1/git-pile.1",
            ],
        ),
    ],
    platforms="any",
)
