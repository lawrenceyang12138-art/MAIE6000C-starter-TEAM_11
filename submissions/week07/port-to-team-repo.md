# Porting B's work into the team repository

Owner: B (read files). Measured on 2026-10-15 against the team repository at
`abacacd` on `main`.

This note exists because the obvious way to move the work across does not
work, and finding that out took a real attempt rather than a guess.

## The two repositories do not share a history

The personal repository and `MAIE6000C-starter-TEAM_11` were both started from
the same course starter, but not from each other. Their first commits are
different objects (`97ffb293` and `abacacd`). Comparing the two starters now,
exactly one file differs - the `Dockerfile` - and only in blank lines and a
trailing newline; the commands in it are the same.

So this does not work:

```
git merge feat/w7-data-layer
# fatal: refusing to merge unrelated histories
```

Forcing it with `--allow-unrelated-histories` would be worse: with no common
ancestor every file that either side changed becomes an add/add conflict, which
means sixty-odd conflicts to resolve by hand.

## What does work, and was verified

Replaying B's commits on top of the team's `main`:

```
git clone https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11.git
cd MAIE6000C-starter-TEAM_11
git remote add personal https://github.com/Exile-Zhang-T/MAIE6000C-starter-jintong-zhang.git
git fetch personal
git checkout -b w7-parsing origin/main
git rebase --onto origin/main personal/main personal/feat/w7-data-layer
```

Result: **every commit on the branch replayed, zero conflicts.** The replay was
re-run after every addition and has never produced a conflict, so the exact
count matters less than the fact that it keeps holding; what matters is that
the branch is replayed, not merged. The commits are re-created with new hashes,
which is expected when the history underneath them changes; the content is
identical.

The replayed tree then runs under the same container as the personal
repository:

```
docker compose run --rm --no-deps \
  -v "$PWD/services:/app/services" -v "$PWD/tests:/app/tests" \
  -v "$PWD/scripts:/app/scripts" -v "$PWD/alembic:/app/alembic" \
  api pytest -q
```

Measured side by side in the same minute: **93 passed, 1 skipped in the team
tree against 95 passed, 1 skipped in the personal repository** (last run). The
gap of two is not a judgement call: the team repository still
contains `tests/integration/test_api_integration.py python`, the filename with
a space and no extension, so pytest never collects those two tests. Renaming
it restores them; that is the Week 3 fix, which exists on the personal
repository and has not been carried into the team repository.

The team's Week 4 branch (`week04-architecture-proposal`) changes `README.md`,
`docs/architecture.md` and `submissions/week04/README.md`. B's commits touch
none of those three files, so this can land before or after that proposal is
merged without either one disturbing the other.

## A second route, if the team prefers one commit

If the team lead would rather not add eighteen commits to review, the same
content can land as a single commit:

```
# in the personal repository
git diff origin/main..feat/w7-data-layer > w7-parsing.patch

# in the team repository, on a fresh branch off main
git checkout -b w7-parsing
git apply w7-parsing.patch
git add -A && git commit -m "Add B's parsing, evidence and review slice"
```

The patch touches no shared decision that the team has already made: the four
relation tables are still listed as a proposal for A in
`handover-to-A.md`.

## What was deliberately not done

No branch was pushed to the team repository, and nothing was merged into its
`main`. A dry run showed the push would be accepted, so write access is already
in place; the remaining step is a decision, not a permission.

Two things in the team repository are outside B's slice and remain open:
`files.current_version_id` is still never set, so an evidence read would report
every passage as stale, and no route exposes the handlers yet.
