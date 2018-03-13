.PHONY = pycheck

pycheck:
	flake8 --max-line-length=100 --show-source \
		git-mbox-prepare \
		git-pile \
		*.py \
		git_pile/*.py
