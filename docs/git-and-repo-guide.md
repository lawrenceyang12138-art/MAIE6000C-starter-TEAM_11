# Git, GitHub, and this repository: a working guide

For Team 11. Written because three of us said the toolchain is the part we are
least sure about, and because the milestone depends on it. Everything below is
grounded in this repository, not in a generic tutorial.

---

## Part 1 - What this repository is

It is four services that share one codebase and start together with Docker.

```
browser
   |  HTTP
services/api/app/main.py        the only service the outside world talks to
   |  writes a row into jobs
PostgreSQL                      the source of truth for state
   |  polled every 2 seconds
services/worker/app/main.py     claims a job and does the slow work
   |  HTTP
services/ai/app/main.py         internal service, not reachable from outside
   |  result written back
PostgreSQL                      now readable through the API
```

`services/common/` holds what all four share: the database models, the request
and response schemas, the settings, and the database connection.

The rule that shapes everything: **slow work happens in the worker, never
inside an API request.** A user submitting something gets an answer
immediately; the model call or the PDF parsing happens afterwards.

### Where each workstream writes

| Workstream | Owns |
| --- | --- |
| A - files and infrastructure | `services/worker/app/main.py` (the dispatch loop), the shared schema decisions, the API routes |
| B - reading files | `services/parsing/`, the four evidence scripts in `scripts/`, the parsing and relation migrations, `tests/` for that slice, `evidence/`, `submissions/week07/` |
| C - retrieval and models | `services/ai/`, the search path |
| D - interface and acceptance | the browser pages, `submissions/`, the demo script |

The point of the split is that nobody edits the same file as somebody else. If
you need a change in someone else's area, ask them rather than editing it.

---

## Part 2 - Git's mental model in four places

Almost every confusing thing about Git comes from not knowing which of four
places a change is currently in.

```
your files on disk      ->  the staging area      ->  a local commit      ->  GitHub
   "working tree"            "the index"              "history"             "remote"
```

1. **Working tree.** The files you are editing right now.
2. **Staging area.** What you have marked to include in the next commit.
3. **Local commit.** A saved snapshot in your own copy of the history. Nothing
   has been shared yet.
4. **Remote.** GitHub. Only changes you `push` get there.

`git status` tells you where everything is. If you are ever unsure, run it.

A file is in one of three states: unmodified, modified, or staged. That is the
entire model.

Two consequences worth internalising:

- **A commit is local and cheap.** You can make twenty of them and change your
  mind. Nothing is public until you push.
- **A push is public.** That is the moment other people, including the
  instructor, can see it.

---

## Part 3 - The commands you will actually type

### Seeing where you are

```
git status                      what has changed, what is staged
git branch --show-current       which branch am I on
git log --oneline -10           the last ten commits
git diff                        unstaged changes, line by line
git diff --staged               what is about to be committed
```

### Saving work

```
git add <file>                  stage one file
git add -A                      stage everything
git commit -m "message"         save a snapshot locally
```

Write the commit message as what the change does and why, not "update".

The lead asked for messages specific enough that a reader can tell what each
commit changed. Measured on this branch afterwards: 54 commits, 39 with a
subject *and* a body, 15 with a subject only - and fourteen of those fifteen
are the same shape, `Re-measure the port after ...`, written while chasing a
number that a previous commit had moved.

Two lessons, both worth more than the tidier history they cost:

- **A number that a change moves belongs in that change.** Those fourteen are
  bookkeeping commits: each one updates a table in a document after the commit
  before it changed a test count. They should have been folded in, and one
  clear commit would have said more than two.
- **A body is where the reason lives.** The subject says what changed; the body
  says why, what was measured, and what was rejected. A reader six days later
  only has the body.

Those messages were then rewritten, on the owner's request, into bilingual
messages with a fuller body - while the branch was minutes old, unreviewed, and
with nobody standing on it. That window is the only reason it was safe, and it
is now closed: a branch that a teammate has pulled must be corrected by adding
commits, not by moving the commits they already have. **Rewriting published
history is acceptable exactly once, immediately, and never again.** If the
history should look tidier than that, the person merging can squash it, which
changes nothing for anyone who already has the branch.

### Branches

```
git switch -c my-branch         create a branch and move onto it
git switch main                 move back to main
git branch                      list local branches
git branch -d my-branch         delete a branch that is merged
git branch -D my-branch         delete one that is not
```

A branch is just a movable label pointing at a commit. Creating one costs
nothing.

### Sharing

```
git push -u origin my-branch    send a branch to GitHub for the first time
git push                        send later commits on a branch already there
git fetch                       get others' changes without touching your files
git pull                        fetch and merge into your current branch
```

### Undoing things

```
git restore <file>              throw away uncommitted edits to a file
git restore --staged <file>     unstage, keeping the edit
git revert <commit>             make a new commit that undoes an old one
git switch -c rescue <commit>   go back and look, without losing anything
```

`git revert` is the safe way to undo something already pushed, because it adds
history rather than rewriting it. **`git reset --hard` is not in this list on
purpose:** it deletes uncommitted work with no recovery.

---

## Part 4 - The workflow the team uses

```
1. branch       git switch -c feature/thing
2. work         edit files, run the tests
3. commit       git add -A && git commit -m "..."
4. push         git push -u origin feature/thing
5. pull request open it on GitHub, let CI run
6. merge        merge into main once CI is green
7. tag          tag main, and only then
```

**CI runs on pull requests, not on pushes to a branch.** `.github/workflows/ci.yml`
triggers on `push` to `main` and on every `pull_request`. So a branch that has
been pushed but has no pull request shows no green tick, and that is not a
failure - it just has not been checked yet. Opening the pull request is what
starts the three checks CI runs: `ruff check .`, `alembic upgrade head` against
an empty PostgreSQL, and `pytest -q tests/unit tests/integration`.

**Why the tag goes last.** A tag is a promise that says "this exact state is
what I want reviewed". If you tag before you finish, a reviewer looks at
something you have already moved on from. The course states this directly:
never assume the latest state will be reviewed when a tag exists.

**Why the tag is on main, not on the branch.** The branch may be deleted after
the merge. Main is what the team continues from.

**The team repository is not a fork of this one.** The two repositories were
both started from the course starter, so they have no common ancestor and
`git merge` refuses with "unrelated histories". Work moves between them by
replaying the commits, not by merging. The verified recipe is in
`submissions/week07/port-to-team-repo.md`.

---

## Part 5 - The mistakes you will make, and the fixes

**"I committed to main by accident."** If main has not been pushed, move the
commit onto a branch and put the label back where the remote says it belongs:

```
git switch -c my-feature       # the commit comes with you
git branch -f main origin/main # move the label only; nothing is deleted
git switch my-feature
```

`git branch -f` moves a branch label. It does not touch your working files the
way `git reset --hard` does, which is why it is the recipe here. If main has
already been pushed, leave it alone and fix forward with a new commit.

**"I am on the wrong branch."** This actually happened in this project. Work
was done on a temporary branch, then the file being looked for appeared to be
missing, because that branch predates the change. `git branch --show-current`
would have answered it in one second. Always check it before wondering where a
file went.

**"A file I know exists is not there."** Almost always the wrong branch, not a
deleted file. Check the branch first, then `git log --oneline --follow <file>`.

**"I deleted something and committed it."**

```
git restore <file>            # if not committed yet
git checkout HEAD~1 -- <file> # take it back from the previous commit
```

**"I pushed something wrong."** Do not rewrite history. Make a commit that
fixes it.

**"It says detached HEAD."** You are looking at a commit rather than a branch.
Nothing is lost. `git switch main` returns you.

**"There is a merge conflict."** Git has written both versions into the file,
between `<<<<<<<` and `>>>>>>>`. Edit the file until it says what you want,
delete the markers, then `git add` and `git commit`.

**"It asks for a username and password."** See Part 6.

**"My pushed branch has no green tick."** Continuous integration runs when a
pull request is opened, not when a branch is pushed. See Part 4.

**"The api container keeps restarting after I pulled new code."** It probably
exits with `FAILED: Can't locate revision identified by ...`. The image holds
its own copy of the migration files, and the api container applies them on
start; a container built before the newest migration cannot serve a database
that already has it. Restarting does not help, because the image is still the
old one:

```
docker compose up -d --build
```

The general rule: **new dependencies or new migrations mean rebuild, not
restart.** That flag costs a minute and saves an afternoon.

---

## Part 6 - Authentication

GitHub stopped accepting account passwords for Git operations. HTTPS pushes need
a **personal access token**, which is a password scoped to specific
permissions and with an expiry date.

1. github.com/settings/tokens -> Generate new token (classic)
2. Note: anything recognisable, e.g. "Mac terminal"
3. Expiration: 90 days
4. Scopes: **tick `repo` only**
5. Generate, then copy the `ghp_...` value immediately - it is shown once

When `git push` asks, the username is your GitHub username and the password is
the token. Pasting shows no characters; that is normal. macOS stores it in the
keychain afterwards.

**The token is a password.** Do not commit it, paste it into a chat, or put it
in a file in the repository.

---

## Part 7 - This repository right now

**This part deliberately does not pin commit hashes or counts.** An earlier
version of it did, and every commit afterwards made it wrong - which a reader
then has to notice for themselves. Ask the repository instead; the answers are
always current:

```
git branch -vv                      # local branches and what they track
git log --oneline -1 origin/main    # where the shared line is
git rev-list --count origin/main..feat/w7-data-layer   # how far ahead the work is
git tag -l                          # the checkpoint tags
```

Branches: `main` (the shared line), `readiness/w03-fix-test-collection` (the
Week 3 fix), and `feat/w7-data-layer` (the read-files work). A team copy of the
same work sits on the team repository as `w7-parsing`. Tags: `w03-readiness`.

Nothing is merged into `main` on either repository yet. Because no pull request
has been opened, CI has never run on the branch; the commands CI would run were
checked locally instead, and `submissions/week07/evidence-final.md` lists them
with their results.

To see what is on it:

```
git log --oneline main..feat/w7-data-layer     # the commits not on main
git diff --stat main..feat/w7-data-layer       # the files they touch
```

To open the pull request that starts CI:

```
https://github.com/Exile-Zhang-T/MAIE6000C-starter-jintong-zhang/compare/main...feat/w7-data-layer
```

---

## One habit worth keeping

Before every commit, run the tests. A commit that breaks them turns a
five-minute fix into a half-hour hunt, and on a shared branch it breaks
everybody else too.
