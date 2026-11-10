# Herdr profiles: the repo is the source, ~/.config/herdr-app is where Herdr reads.
PY := python3
TOOL := $(PY) scripts/herdr_profiles.py

.PHONY: help install status pull uninstall check test upstream banner export export-check

help:
	@echo "make install    copy the repo into the Herdr home (safe: stops on files edited in Herdr)"
	@echo "                 ARGS=\"ideas\" only the core and ideas (default: every profile not uninstalled)"
	@echo "                 ARGS=\"--set ideas.folder=~/notes\" answers a new profile's question"
	@echo "make status     what differs between the repo and the Herdr home"
	@echo "make pull       developers: bring files edited in Herdr back into the repo"
	@echo "make check      validate JSON and run herdr-app check on every mod"
	@echo "make test       run the installer's tests"
	@echo "make upstream   developers: what a new Herdr changed in what core/ cloned"
	@echo "                 ARGS=--diff shows it; ARGS=--save records it once merged"
	@echo "make banner     developers: render docs/banner/banner.html to docs/banner.png (Chrome)"
	@echo "make uninstall  remove what install wrote and added (ARGS=\"ideas\": only that profile)"
	@echo "make export     DEST=<new folder> AUTHOR=\"Name <email>\": HEAD as a new one-commit repo, checked"
	@echo "make export-check DEST=<folder>  check an existing export again"

install:
	@$(TOOL) install $(ARGS)

status:
	@$(TOOL) status

pull:
	@$(TOOL) pull

uninstall:
	@$(TOOL) uninstall $(ARGS)

check:
	@$(TOOL) check

upstream:
	@$(TOOL) upstream $(ARGS)

test:
	@$(PY) -m unittest discover -s tests

CHROME ?= /Applications/Google Chrome.app/Contents/MacOS/Google Chrome

banner:
	@"$(CHROME)" --headless=new --disable-gpu --hide-scrollbars --allow-file-access-from-files \
	  --force-device-scale-factor=2 --default-background-color=00000000 --window-size=1280,600 \
	  --screenshot=docs/banner.png "file://$(CURDIR)/docs/banner/banner.html" >/dev/null 2>&1
	@echo "docs/banner.png"

export:
	@test -n "$(DEST)" && test -n "$(AUTHOR)" || { echo 'usage: make export DEST=<new folder> AUTHOR="Name <email>"'; exit 2; }
	@$(PY) scripts/export_public.py "$(DEST)" --author "$(AUTHOR)"

export-check:
	@test -n "$(DEST)" || { echo 'usage: make export-check DEST=<folder>'; exit 2; }
	@$(PY) scripts/export_public.py --check "$(DEST)"
