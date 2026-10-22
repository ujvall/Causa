# Contributing to CAUSA

CAUSA has a single contributor and owner: **ujvall**. These rules apply to all work on the repository, including work done with AI assistance.

## Branches and pull requests

1. `main` is the stable branch.
2. Do not develop directly on `main`.
3. Every phase or substantial change uses its own feature branch, created from the latest `main` after earlier work has been merged.
4. Push development changes to that feature branch.
5. Open a pull request targeting `main`.
6. The owner reviews and merges pull requests.
7. Never merge a pull request or change `main` on the owner's behalf unless the owner explicitly asks.
8. Never force-push, rewrite history, or delete remote branches without explicit permission.

Branch names follow the phase plan:

| Work | Branch |
|---|---|
| Phase 4: optimizer | `phase-4-optimizer` |
| Phase 5: C code generation | `phase-5-codegen` |
| Phase 6: runtime | `phase-6-runtime` |

Other substantial changes use a short descriptive name, for example `fix-lexer-crlf` or `docs-ir-schema`.

## Before committing and pushing

9. Run the relevant tests with Python 3.11 and make sure they pass:

   ```bash
   py -3.11 -m unittest discover -s tests
   ```

10. Commit with the owner's configured Git identity (`git config user.name` / `user.email`). Do not commit under another identity.

## Sole-contributor rules

* Do not add collaborators, bots or other accounts to the repository.
* Do not add `Co-authored-by` trailers for AI assistants or bots.
* Do not change repository ownership, visibility, permissions or branch protection.
* Do not add automation (for example GitHub Actions) that commits as a bot.

## Local-only files

`graphify-out/` (a generated knowledge graph with machine-specific paths), Python caches and virtual environments are ignored by `.gitignore` and are never committed.
