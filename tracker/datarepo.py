"""Private data repository: shallow clone, commit and push with git.

The token only lives in the remote URL of a temporary clone; git output is
redacted before it can reach the logs.
"""
import os
import subprocess
from pathlib import Path

from . import env

BOT_NAME = "film-tracker-bot"
BOT_EMAIL = "film-tracker-bot@users.noreply.github.com"


class DataRepoError(RuntimeError):
    pass


def _git(args, cwd=None):
    proc = subprocess.run(
        ["git", "-c", "credential.helper=", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if proc.returncode != 0:
        command = next(a for a in args if not a.startswith("-") and "=" not in a)
        raise DataRepoError(f"git {command} failed: {env.redact(proc.stderr.strip())}")
    return proc.stdout


def clone(dest):
    """Shallow-clone the data repo into `dest` (works for an empty repo too)."""
    dest = Path(dest)
    url = f"https://x-access-token:{env.require('DATA_TOKEN')}@github.com/{env.data_repo()}.git"
    _git(["-c", "init.defaultBranch=main", "clone", "--quiet", "--depth", "1", url, str(dest)])
    _git(["config", "user.name", BOT_NAME], cwd=dest)
    _git(["config", "user.email", BOT_EMAIL], cwd=dest)
    return dest


def commit_and_push(repo_dir, message):
    """Commit everything and push the current branch. False if nothing changed."""
    _git(["add", "-A"], cwd=repo_dir)
    if not _git(["status", "--porcelain"], cwd=repo_dir).strip():
        return False
    _git(["commit", "--quiet", "-m", message], cwd=repo_dir)
    _git(["push", "--quiet", "origin", "HEAD"], cwd=repo_dir)
    return True
