# git-pile
Manage a pile of patches on top of a git branch

## Quickstart

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
the entire series by targeting the the pile directory instead of the normal
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
