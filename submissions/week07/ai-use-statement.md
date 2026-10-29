# AI Use Statement

Team 11 · W07 midterm milestone · 2026-10-29

## Tools used

Generative AI assistants were used by team members during this milestone:

- DeepSeek
- ChatGPT
- Kimi
- Codex
- WorkBuddy

## Purpose of use

- code scaffolding and refactoring suggestions (routes, schemas, tests)
- debugging suggestions (row locking, concurrency tests, test isolation)
- documentation drafting and editing
- checking our own claims against the shared contract

## Materially affected areas

- tests — `tests/` (unit, integration and PostgreSQL concurrency cases)
- milestone materials — `submissions/week07/` (README, report, per-role sections, evidence)

## Verification performed

- **correctness checks**: every number in this folder comes from a command run in this
  repository. Queue invariants were mutation-checked: removing the guard must turn the
  concurrency tests red.
- **limitations noticed**: AI produced no number that a human did not run; no commit was made
  without tests being run locally; nothing generated was committed unread.

## Responsibility statement

We confirm that we understand and can explain all submitted work associated with this statement.
