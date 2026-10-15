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
| B - reading files | `services/parsing/`, `scripts/verify_page_attribution.py` |
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

**Why the tag goes last.** A tag is a promise that says "this exact state is
what I want reviewed". If you tag before you finish, a reviewer looks at
something you have already moved on from. The course states this directly:
never assume the latest state will be reviewed when a tag exists.

**Why the tag is on main, not on the branch.** The branch may be deleted after
the merge. Main is what the team continues from.

---

## Part 5 - The mistakes you will make, and the fixes

**"I committed to main by accident."** Move the commit to a branch, then put
main back:

```
git switch -c my-feature      # the commit comes with you
git switch main
git reset --hard origin/main  # only safe if nothing you need is on main
```

The safer variant, if main has already been pushed: leave it, and make the fix
in a following commit.

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

```
main                              ff4e718  the shared line, pushed
readiness/w03-fix-test-collection 93accfd  the W03 branch, pushed
feat/w7-data-layer                9e04f89  B's work, NOT pushed yet
```

Tags: `w03-readiness`.

`feat/w7-data-layer` carries twenty commits, thirteen of them from the
read-files workstream. Nothing on it is visible to anyone else until it is
pushed.

To see what is on it without pushing:

```
git log --oneline main..feat/w7-data-layer     # the commits not on main
git diff --stat main..feat/w7-data-layer       # the files they touch
```

To share it, once the token is configured:

```
git switch feat/w7-data-layer
git push -u origin feat/w7-data-layer
```

Then open a pull request on GitHub and let CI run before merging.

---

## One habit worth keeping

Before every commit, run the tests. A commit that breaks them turns a
five-minute fix into a half-hour hunt, and on a shared branch it breaks
everybody else too.
