"""The profile tool: builds Herdr profiles from this repo and syncs them with a Herdr home.

Modules, from the bottom up:

  files     reading and writing files safely (atomic writes, hashes, JSON, the write hook)
  jsonedit  the smallest textual edit to a JSON file of the person's own
  home      the Herdr home: where things go, what Herdr ships
  manifest  what install wrote and added, which profiles and checkout; the journal
  herdr     the herdr-app binary and its version
  spec      profile.json: loading, validation, the package model
  build     layouts built from a recipe (base + inserts + settings + switcher)
  plan      every file a set of packages installs, and its state in a home
  personal  first-time entries in the person's profiles.json and keys.json
  upstream  the clones in core/ against the Herdr originals they came from (upstream/)
  commands  status, install, pull, uninstall, check
  cli       the command line

Stdlib only; Python 3.9+.
"""
