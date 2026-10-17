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

Measured side by side in the same minute (last run): **103 passed, 1 skipped in
the personal repository against 101 passed, 1 skipped in the team tree.** The
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

If the team lead would rather not review a whole branch's worth of commits, the
same content can land as a single commit:

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

## What has been done, and what has not

The branch **is now on the team repository**: `w7-parsing`. Its size and its
tip are deliberately not written down here - both change with every commit, and
an earlier version of this section quoted a commit that a later rewrite made
unfindable. Ask the repository instead:

```
git ls-remote origin | grep w7-parsing
git rev-list --count origin/main..origin/w7-parsing
```

Two properties make it cheap for the team to deal with:

- **`main` is untouched** - it is still `abacacd`, the starter, exactly as the
  team agreed: nobody commits to `main`, everyone pushes a branch and the merge
  happens at the freeze.
- **It is a descendant of `main`**, so merging it is a fast-forward with
  nothing to resolve. The work was replayed onto the team's own starting point
  rather than merged across two unrelated histories, which is what makes that
  true.

To merge it, whoever owns the freeze needs one command:

```
git switch main
git merge --ff-only w7-parsing
```

**Two things that are still open, and are the team's to decide:**

1. **CI does not run on branch pushes.** `.github/workflows/ci.yml` fires on
   `pull_request` and on pushes to `main`, so this branch - like every member's
   branch - gets no checks until a pull request exists. Either open a PR per
   branch, or the workflow's trigger gains the member branches. Otherwise the
   first time anyone sees whether the branches work together is at the merge.
2. **The repository still hides two tests.** `tests/integration/` contains
   `test_api_integration.py python` - a space in the name, no extension - so
   pytest never collects it and two integration tests never run anywhere in
   this repository, including in CI. It is a one-line rename; this branch does
   not carry it, because it is Week 3 work rather than Week 7 work.

Two things in the team repository are outside B's slice and remain open:
`files.current_version_id` is still never set, so an evidence read would report
every passage as stale, and no route exposes the handlers yet.
