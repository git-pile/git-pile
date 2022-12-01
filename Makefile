NOSETESTS := $(shell command -v nosetests-3 || command -v nosetests)
MKDIR_P := mkdir -p

SUBCMDS_NOHELP = init
SUBCMDS = init setup genpatches genbranch format-patch am genlinear-branch baseline destroy reset
MAN_PAGES = $(addprefix git-pile-, $(addsuffix .1, $(SUBCMDS)))

pycheck:
	@-flake8 --show-source git-*
	@-flake8 --show-source

check:
	$(NOSETESTS)

FORCE:

git-pile-%.1: FORCE
	@$(MKDIR_P) man
	@echo -e "#!/bin/bash\nexec ./git-pile $* \"\$$@\"" > git-pile-wrapper-$*
	@chmod +x git-pile-wrapper-$*
	help2man -n "git pile $*" -N -s 1 --no-discard-stderr ./git-pile-wrapper-$* > man/man1/$@
	@rm git-pile-wrapper-$*

man: $(MAN_PAGES)
	help2man -n "git pile" -N -s 1 --no-discard-stderr ./git-pile > man/man1/git-pile.1

.PHONY: all pycheck check man
