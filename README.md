# git-pile
Manage a pile of patches on top of a git branch

## Quickstart

### Running git-pile

git-pile follows the git naming convention for binaries so we can use it as a
subcommand to git. Either of the following forms work if the git-pile is in the
search PATH:

```bash
$ git pile -h
$ git-pile -h
```

For autocomplete to work you need Python's argcomplete module installed.
In the first case you also need to source the bash autocomplete file
`extra/git-pile-complete.sh` so git knows how to complete the subcommand.

You can also install git-pile as a python package, although that's not
recommended for now since it's not stable enough:

```bash
$ ./setup.py install
```

In case a `--user` option is provided to the command above it will install under `$HOME`
directory and bash completion file will be at `$XDG_DATA_HOME/git-pile/bash_completion`.
There isn't a standard user directory for bash completion we can install to, so
the user is expected to source this file.

### Repository initialization

Initialize empty pile:

```bash
$ git pile init
```

Now you have a (orphan) pile branch to keep track of patch files to be managed
on top of the master branch. Branch names may be changed via options to
git-pile init.

```bash
$ git checkout -b newfeature
$ echo "platform 16" >> platforms.txt
$ git add platforms.txt
$ git commit "add new platform"
```

The result can be prepared to send to a mailing list in the same vein as how
git-format-patch works:

```bash
$ git pile format-patch -o /tmp/patches
/tmp/patches/0000-cover-letter.patch
/tmp/patches/0001-add-new-platform.patch
```

Or that can be turned into the patches we are tracking:

```bash
$ git pile genpatches master..newfeature
$ cd pile
$ git add -A
$ git commit -m "add platform"
$ git genbranch
```

The last command will regenerate the "internal" branch using the patches from
this "newfeature" branch.

The cover-letter in a git-pile generated patch series always contain the diff
of the original state of the tree to the current state. It may be used to apply
the entire series by targeting the pile directory instead of the normal
working directory.

```bash
$ # machine 2
$ cd pile
$ git am /tmp/patches/0000-cover-letter.patch
$ git genbranch
```

Patches may be reordered, added in the middle, reworded etc. By going through
the genpatches + genbranch cycle we can always re-generate the branch and keep
the history of what was done.
