# Working on this repo

How Zac wants code changes made (set 2 Nov 2026):

- Edit the files directly in this folder on Zac's Mac (the linked computer's
  folder "Cowork Base/03 Code Projects/Football stats"), the copy he has open
  in VS Code. Do not make the changes in a cloud clone.
- Ask before changing files: say which files and what changes, then wait for
  a yes. One yes covers the change described, not later ones.
- Do not commit, push, open pull requests or merge. Zac reviews the changes in
  VS Code's Source Control panel and commits and pushes them himself.
- Do not run git commands that change the repo here (commit, checkout, reset,
  stash, pull): the linked shell cannot delete files, so git leaves .lock files
  behind. Reading (git status, git diff, git log) is fine.
- After a change, list the files changed and the command to test it, e.g.
  `.venv/bin/python -m pytest -q tests/test_x.py`, for Zac to run in VS Code's
  terminal (the Mac's .venv does not run in the linked Linux shell).
- Write each file with an edit in place (python read-modify-write or sed),
  never by retyping a whole file from earlier output.
