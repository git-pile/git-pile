.PHONY = pycheck

pycheck:
	@-flake8 --show-source git-*
	@-flake8 --show-source

check:
	nosetests-3
