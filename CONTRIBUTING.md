# Contributing to CAUSA

CAUSA has a single contributor and owner: **ujvall**. These rules apply to all work on the repository, including work done with AI assistance.

## Branches

From Phase 5 onward the owner has chosen a direct-to-`main` workflow:

1. Work happens directly on `main`; no feature branches and no pull requests unless the owner asks for them.
2. Commit only after the tests pass, then push to `origin/main`.
3. Never force-push, reset, rewrite history, or delete branches without the owner's explicit permission.
4. If a push is rejected because `main` changed remotely, fetch and reconcile without discarding either side's work.

(Phases 1–4 used feature branches and pull requests #1 and #2; those branches have been merged and deleted.)

## Before committing and pushing

5. Run the relevant tests with Python 3.11 and make sure they pass:

   ```bash
   py -3.11 -m unittest discover -s tests
   ```

6. Commit with the owner's configured Git identity (`git config user.name` / `user.email`). Do not commit under another identity.

## Sole-contributor rules

* Do not add collaborators, bots or other accounts to the repository.
* Do not add `Co-authored-by` trailers for AI assistants or bots.
* Do not change repository ownership, visibility, permissions or branch protection.
* Do not add automation (for example GitHub Actions) that commits as a bot.

## Local-only files

`graphify-out/` (a generated knowledge graph with machine-specific paths), Python caches and virtual environments are ignored by `.gitignore` and are never committed.
