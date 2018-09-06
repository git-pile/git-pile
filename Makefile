.PHONY = pycheck

NOSETESTS := $(shell command -v nosetests-3 || command -v nosetests)

pycheck:
	@-flake8 --show-source git-*
	@-flake8 --show-source

check:
	$(NOSETESTS)
