"""The profile tool: builds Herdr profiles from this repo and syncs them with a Herdr home.

Modules, from the bottom up:

  files     reading and writing files safely (atomic writes, hashes, JSON)
  home      the Herdr home: where things go, what Herdr ships
  manifest  what install wrote and added, and which profiles are installed
  herdr     the herdr-app binary and its version
  spec      profile.json: loading, validation, the package model
  build     layouts built from a recipe (base + inserts + settings + switcher)
  plan      every file a set of packages installs, and its state in a home
  personal  first-time entries in the person's profiles.json and keys.json
  commands  status, install, pull, uninstall, check
  cli       the command line

Stdlib only; Python 3.9+.
"""
