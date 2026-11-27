"""Run an A-specified commit/config on an isolated, keyword-only Role C stack."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from scripts.c_format_fixtures import REPO, STAGE, SUITE
from scripts.c_search_suite import require

COMPOSE = REPO / "compose.c-formats.yaml"
MOUNT = "c-formats-v1"
DATABASE = "c_format_gate"
REVISION = "org.opencontainers.image.revision"
FIXED = {"EMBEDDING_ENABLED": "false", "EMBEDDING_AUTO_PREPARE": "false",
         "SEARCH_PAGE_NAVIGATION_ENABLED": "true", "HF_HUB_OFFLINE": "1",
         "TRANSFORMERS_OFFLINE": "1"}
SWITCHES = {"TEXT_PARSING_ENABLED", "DOCX_PARSING_ENABLED"}


def read_flags(path: Path, scope: set[str]) -> dict:
    """Only a small, non-secret flags file, not an application .env or Compose override."""
    flags = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.strip().partition("=")
        require(sep and key not in flags, "invalid or duplicate flag")
        require((key in SWITCHES and value in {"true", "false"}) or
                (key == "TEXT_MAX_BYTES" and value.isascii() and value.isdecimal()
                 and 0 < int(value) <= 2 * 1024 * 1024), "unknown setting or invalid flag value")
        flags[key] = value
    require(SWITCHES <= flags.keys(), "A must explicitly set both parser switches")
    require(not scope.intersection({"txt", "md"}) or flags["TEXT_PARSING_ENABLED"] == "true",
            "text parser is disabled for the requested scope")
    require("docx" not in scope or flags["DOCX_PARSING_ENABLED"] == "true",
            "DOCX parser is disabled for the requested scope")
    return flags


def command(*args, **kwargs):
    return subprocess.run(args, cwd=REPO, check=True, **kwargs)


def output(*args, **kwargs):
    return command(*args, stdout=subprocess.PIPE, encoding="utf-8", **kwargs).stdout.strip()


def start(args, report):
    """Build from git archive, never the mutable checkout or a pre-existing app image."""
    import json

    sha = args.candidate_sha
    flags = read_flags(args.flags, set(args.formats))
    require(re.fullmatch("[0-9a-f]{40}", sha) and output("git", "rev-parse", f"{sha}^{{commit}}")
            == sha, "fetch A's exact full commit first")
    project = f"team11-c-format-{args.run_id}"
    # No existing deployment or data is ever migrated, reset or reused by this tool.
    scope_filter = f"label=com.docker.compose.project={project}"
    require(not output("docker", "ps", "-aq", "--filter", scope_filter)
            and f"{project}_data" not in output("docker", "volume", "ls", "-q").splitlines(),
            "project/volume already exists; use a fresh run ID")
    tag = f"team11-c-format-candidate:{sha}"
    with tempfile.TemporaryFile() as context:
        command("git", "archive", "--format=tar", sha, stdout=context)
        context.seek(0)
        command("docker", "build", "--label", f"{REVISION}={sha}", "-t", tag, "-", stdin=context)
    env = dict(os.environ, C_FORMAT_IMAGE=tag, C_FORMAT_FLAGS=args.flags.resolve().as_posix(),
               C_FORMAT_API_PORT=str(args.api_port), C_FORMAT_DB_PORT=str(args.db_port))
    compose = ("docker", "compose", "--env-file", str(SUITE / "no-extra-flags.env"),
               "-f", str(COMPOSE), "-p", project)
    command(*compose, "up", "-d", "--wait", "--pull", "never", "db", "api", "worker", env=env)
    built = output("docker", "image", "inspect", "--format", "{{.Id}}", tag)
    report.update(project=project, image=built, flags=flags, isolation=FIXED, containers={})
    for service in ("api", "worker"):
        ident = output(*compose, "ps", "-q", service, env=env)
        container = json.loads(output("docker", "inspect", ident))[0]
        conf = container["Config"]
        actual = dict(s.split("=", 1) for s in conf["Env"])
        mounts = container["Mounts"]
        require(container["State"]["Running"] and container["Image"] == built
                and conf["Labels"].get(REVISION) == sha, f"wrong running {service} image")
        require(all(actual.get(k) == v for k, v in (flags | FIXED).items()),
                f"wrong running {service} settings")
        require(len(mounts) == 1 and mounts[0]["Destination"] == "/source/c-formats"
                and mounts[0]["Type"] == "bind" and not mounts[0]["RW"], "unexpected mount")
        # Query identities and per-source hashes also bind these bytes to the database.
        report["containers"][service] = {"id": ident, "image": built, "revision": sha,
                                         "source": str(STAGE), "read_only": True}
