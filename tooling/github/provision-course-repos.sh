#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  provision-course-repos.sh --org ORG --template OWNER/TEMPLATE --csv FILE [--visibility private|public] [--dry-run]

Example:
  ./tooling/github/provision-course-repos.sh \
    --org your-org \
    --template your-org/maie6000c-starter-template \
    --csv tooling/github/course-repos.example.csv \
    --visibility private

CSV columns:
  repo_name,display_name,github_users

Notes:
  - github_users should be semicolon-separated
  - no embedded commas are supported in CSV fields
EOF
}

trim() {
  local value="$*"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

run_cmd() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    printf '+'
    for arg in "$@"; do
      printf ' %q' "$arg"
    done
    printf '\n'
  else
    "$@"
  fi
}

create_label_if_needed() {
  local full_repo="$1"
  local name="$2"
  local color="$3"
  local description="$4"

  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "+ ensure label '${name}' on ${full_repo}"
    return
  fi

  gh api --silent "repos/${full_repo}/labels/${name}" >/dev/null 2>&1 && return 0

  gh api --silent --method POST "repos/${full_repo}/labels" \
    -f name="${name}" \
    -f color="${color}" \
    -f description="${description}" >/dev/null
}

ORG=""
TEMPLATE=""
CSV_FILE=""
VISIBILITY="private"
DRY_RUN="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --org)
      ORG="$2"
      shift 2
      ;;
    --template)
      TEMPLATE="$2"
      shift 2
      ;;
    --csv)
      CSV_FILE="$2"
      shift 2
      ;;
    --visibility)
      VISIBILITY="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "${ORG}" || -z "${TEMPLATE}" || -z "${CSV_FILE}" ]]; then
  usage
  exit 1
fi

if [[ ! -f "${CSV_FILE}" ]]; then
  echo "CSV file not found: ${CSV_FILE}" >&2
  exit 1
fi

if [[ "${VISIBILITY}" != "private" && "${VISIBILITY}" != "public" ]]; then
  echo "Visibility must be 'private' or 'public'." >&2
  exit 1
fi

if [[ "${DRY_RUN}" != "true" ]]; then
  gh auth status >/dev/null
fi

VISIBILITY_FLAG="--private"
if [[ "${VISIBILITY}" == "public" ]]; then
  VISIBILITY_FLAG="--public"
fi

{
  read -r _header

  while IFS=, read -r raw_repo_name raw_display_name raw_github_users; do
    repo_name="$(trim "${raw_repo_name:-}")"
    display_name="$(trim "${raw_display_name:-}")"
    github_users="$(trim "${raw_github_users:-}")"

    [[ -z "${repo_name}" ]] && continue
    [[ "${repo_name}" =~ ^# ]] && continue

    full_repo="${ORG}/${repo_name}"
    description="MAIE 6000C repository for ${display_name}"

    echo
    echo "=== Processing ${full_repo} ==="

    if gh repo view "${full_repo}" >/dev/null 2>&1; then
      echo "Repo already exists; skipping creation."
    else
      run_cmd gh repo create "${full_repo}" \
        "${VISIBILITY_FLAG}" \
        --template "${TEMPLATE}" \
        --clone=false \
        --description "${description}"
    fi

    run_cmd gh api --method PATCH "repos/${full_repo}" \
      -f has_issues=true \
      -f has_wiki=false \
      -f delete_branch_on_merge=true >/dev/null

    run_cmd gh api --method PUT "repos/${full_repo}/topics" \
      -H "Accept: application/vnd.github+json" \
      -f names[]=maie6000c \
      -f names[]=fall2026 >/dev/null

    create_label_if_needed "${full_repo}" "milestone-review" "1d76db" "Structured milestone review"
    create_label_if_needed "${full_repo}" "access" "5319e7" "Access or collaborator issue"
    create_label_if_needed "${full_repo}" "ci" "c2e0c6" "CI or automation issue"
    create_label_if_needed "${full_repo}" "docs" "0e8a16" "Documentation work"

    IFS=';' read -ra users <<< "${github_users}"
    for raw_user in "${users[@]}"; do
      user="$(trim "${raw_user}")"
      [[ -z "${user}" ]] && continue
      run_cmd gh api --silent --method PUT "repos/${full_repo}/collaborators/${user}" \
        -f permission=push >/dev/null
    done

    existing_bootstrap_titles="$(
      gh issue list --repo "${full_repo}" --limit 200 --json title --jq '.[].title' 2>/dev/null || true
    )"

    if ! grep -Fq "[BOOTSTRAP] Repo setup checklist" <<< "${existing_bootstrap_titles}"; then
      bootstrap_body=$(
        cat <<EOF
This issue tracks the initial readiness state for this repository.

## Checklist

- [ ] all intended collaborators have access
- [ ] repository boots from a clean clone
- [ ] README is present and current
- [ ] docs/architecture.md exists
- [ ] docs/operations.md exists
- [ ] submissions/week04/ exists
- [ ] submissions/week07/ exists
- [ ] submissions/week13/ exists

## First actions

1. confirm access
2. run the starter stack
3. decide team working conventions
4. open your first scoped issues
EOF
      )

      run_cmd gh issue create \
        --repo "${full_repo}" \
        --title "[BOOTSTRAP] Repo setup checklist" \
        --label docs \
        --body "${bootstrap_body}" >/dev/null
    else
      echo "Bootstrap issue already exists; skipping."
    fi
  done
} < "${CSV_FILE}"

echo
echo "Provisioning complete."
