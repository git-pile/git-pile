#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1+

from os import path as op
from setuptools import setup
from git_pile import __version__
import os
import sys

if sys.version_info < (3, 5):
    sys.exit("Sorry, we need at least Python 3.5.x")

if "install" in sys.argv and "--user" in sys.argv:
    # this is not a standard location, the user still needs to source the file,
    # but at least it's installed somewhere we can document
    datadir = os.environ.get("XDG_DATA_HOME", op.join(op.expanduser('~'), '.local', 'share'))
    bash_completion_dir = op.join(datadir, "git-pile", "bash_completion")
    mandir = op.join(datadir, "man")
else:
    mandir = '/usr/share/man'
    bash_completion_dir = '/etc/bash_completion.d'

setup(
    name="git-pile",
    version=__version__,
    description="Manage a pile of patches on top of git branches",
    url="FIXME",
    maintainer="git-pile contributors",
    include_package_data=True,
    maintainer_email="FIXME@lists.freedesktop.org",
    license="LGPLv2+",
    scripts=["git-pile", "git-mbox-prepare"],
    classifiers=['Intended Audience :: Developers',
                 'License :: OSI Approved',
                 'Programming Language :: Python',
                 'Topic :: Software Development',
                 'Operating System :: POSIX',
                 'Operating System :: Unix'],
    packages=['git_pile'],
    package_data={'git_pile': [
        op.join('data', 'git-cover-order.txt'),
    ]},
    data_files=[
        (bash_completion_dir, ['extra/git-pile-complete.sh']),
        (op.join(mandir, 'man1'), ['man/git-pile-baseline.1',
                            'man/git-pile-destroy.1',
                            'man/git-pile-format-patch.1',
                            'man/git-pile-genbranch.1',
                            'man/git-pile-genpatches.1',
                            'man/git-pile-setup.1',
                            'man/git-pile.1'],
        )
    ],
    platforms='any',
)
