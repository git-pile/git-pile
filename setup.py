#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1+

from setuptools import setup
import sys

if sys.version_info < (3, 3):
    sys.exit("Sorry, we need at least Python 3.3.x")

setup(
    name="git-pile",
    version="0",
    description="Manage a pile of patches on top of git branches",
    url="FIXME",
    maintainer="git-pile contributors",
    maintainer_email="FIXME@lists.freedesktop.org",
    license="LGPLv2+",
    scripts=["git-pile", "git-mbox-prepare"],
    classifiers=['Intended Audience :: Developers',
                 'License :: OSI Approved',
                 'Programming Language :: Python',
                 'Topic :: Software Development',
                 'Operating System :: POSIX',
                 'Operating System :: Unix'],
    platforms='any',
)
