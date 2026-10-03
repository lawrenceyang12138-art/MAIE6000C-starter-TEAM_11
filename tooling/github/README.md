# GitHub Provisioning Tooling

## Purpose

This folder contains a simple `gh` CLI workflow for provisioning course repositories from the starter template.

It can be used for:

- team project repositories
- individual readiness repositories
- any starter-based course repo that needs collaborators added automatically

## Requirements

You need:

- GitHub CLI (`gh`)
- authenticated GitHub access with permission to create repos in the target org/user
- a starter template repository already available

## CSV format

Expected columns:

- `repo_name`
- `display_name`
- `github_users`

`github_users` should be a semicolon-separated list.

Example:

- `fall2026-team-project-orbit,Team Orbit,alice;bob;carol`

## Example usage

```bash
chmod +x tooling/github/provision-course-repos.sh

./tooling/github/provision-course-repos.sh \
  --org your-org-name \
  --template your-org-name/maie6000c-starter-template \
  --csv tooling/github/course-repos.example.csv \
  --visibility private
```

## Dry run

To preview actions without creating anything:

```bash
./tooling/github/provision-course-repos.sh \
  --org your-org-name \
  --template your-org-name/maie6000c-starter-template \
  --csv tooling/github/course-repos.example.csv \
  --visibility private \
  --dry-run
```

## Notes

The script is intentionally simple.

It assumes no embedded commas inside CSV fields.

Re-running it is safe for normal course use: existing repos are skipped, and collaborator setup is retried.
