# git-pile
Manage a pile of patches on top of a git branch

<p align="center">
  <img src="/docs/git-pile-cycle.svg" />
</p>

## Requirements

 - Python >= 3.7
 - git >= 2.20
 - Python modules:
   - argcomplete (optional for shell completion)
   - coverage (optional for tests)

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
In the first case, you also need to source the bash autocomplete file
`extra/git-pile-complete.sh` so git knows how to complete the subcommand.

You can also install git-pile as a python package, although that's still not
recommended since it's being updated frequently.

```bash
$ ./setup.py install
```

OR

```bash
$ ./setup.py install --user
```

In case a `--user` option is provided to the command above it will install
under `$HOME` directory and bash completion file will be at
`$XDG_DATA_HOME/git-pile/bash_completion`.  There isn't a standard user
directory for bash completion we can install to, so the user is expected to
source this file.

### Repository initialization

Initialize a new **empty** pile:

```bash
$ git pile init
```

Now you have a (orphan) pile branch to keep track of patch files to be managed
on top of the master branch. Branch names may be changed via options to
`git pile init`. Like `git init` creates a new repository, `git pile init` will
create a new pile.

Alternatively, if the pile branch already exists in a remote repository (or
even locally) and you want to setup your work tree to use it you should use
the command below:

```bash
$ git pile setup internal/pile internal/embargo-branch
```

In the example above we have a remote called `internal` which has a branch
named `pile` that contains the patch files and a branch named `embargo-branch`
that will be the branch being generated when we apply the patches.

The second argument is optional and if not given the current branch will be
used.

### Develop a new commit and send to mailing list

You can use your normal git flow to develop changes in the project and create
commits. Here is an example that is by no means restricted to git-pile:

```bash
$ git checkout -b newfeature internal/embargo-branch
$ echo "platform 16" >> platforms.txt
$ git add platforms.txt
$ git commit "add new platform"
```

Continuing from the initialization example, we create a new branch with
`internal/embargo-branch` as the base. The result can be prepared to send to a
mailing list in the same vein as how `git format-patch` works:

```bash
$ git pile format-patch -o /tmp/patches
/tmp/patches/0000-cover-letter.patch
/tmp/patches/0001-add-new-platform.patch
```

The cover letter will contain the diff to the pile branch (with patches added
and so on), while the patch files will also be available in isolation: those
are diffs to the result branch, and present to ease review.

If the commit you are adding should not be on top, but rather in the middle
of the long running patch series, you can just move it down in the tree
with `git rebase -i`. In the example below we will move it 10 commits down:

```bash
$ git rebase -i -11

  [ editor opens and you move the commit around. You can also reorder
    commits, edit commit message, etc, etc. Anything you do in an
    interactive rebase you can do here ]

$ git pile format-patch -o /tmp/patches
/tmp/patches/0000-cover-letter.patch
/tmp/patches/0001-old-platform.patch
/tmp/patches/0002-old-platform-2.patch
/tmp/patches/0003-add-new-platform.patch
```

Any patch that needs to be changed in order to accommodate the patch in the
middle of the series will be prepared by `git pile format-patch`.

### Generate the pile from the changed tree

Instead of sending to the mailing list, you can simply transform
the changes from the branch to the physical patches maintained
in the pile branch.

```bash
$ git pile genpatches master..newfeature
$ cd patches
$ git add -A
$ git commit -m "add platform"
$ git pile genbranch
```

This generates the patches, saving the final state in the patch series, and
then recreates `embargo-branch` locally. Patches may be reordered, added in the
middle, reworded etc. By going through the genpatches + genbranch cycle we can
always re-generate the branch and keep the history of what was done, i.e.
maintain the history of how the patches were changed/added/removed.

### Apply a patch series to the pile

The cover-letter in a git-pile generated patch series (i.e. the one generated
by `git pile format-patch`) always contain the diff of the original state of the
tree to the current state. It may be used to apply the entire series by
targeting the patches directory instead of the normal working directory.

```bash
$ # machine 2
$ cd pile
$ git am /tmp/patches/0000-cover-letter.patch
$ git genbranch
```

This will apply the entire series that was received (even if it was a 10 patches
series, only the specially-formatted cover-letter needs to be applied).

### Destroying the pile

If anything goes wrong and you'd like to start over, you can call the `destroy`
command. This will remove all configuration saved by git-pile, the pile branch
itself and the worktree directory it was using. If you have a backup of the
patches (either manual or if the pile branch is in a remote repository), this
is pretty safe to do and allows you to redo the configuration.
