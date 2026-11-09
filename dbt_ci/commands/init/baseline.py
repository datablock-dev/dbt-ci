"""
Find the manifest a pull request should be compared against: the one at its merge base.

Comparing against the latest production manifest counts everything merged and deployed
since the branch was created as the pull request's own change. `init --compare-to`
decides what to compare against:

- `auto` (the CLI default): the merge base when git shows the branch has commits of its
  own, otherwise the latest state. Any fallback is logged at info level.
- `merge-base`: always the merge base, warning when it cannot be used.
- `latest`: the latest state, as before this option existed.

The merge base's manifest is found in this order:

1. A manifest archived for that commit, or the nearest base-branch commit before it,
   next to the state: `<state-uri directory>/<sha>/manifest.json`, or
   `<state dir>/<sha>/manifest.json` for a local state. `finalize` keeps these copies.
2. A manifest built on the spot: the merge base is checked out into a temporary git
   worktree and parsed with dbt, using the reference target and vars.
3. Otherwise the latest state.

Only the comparison uses the baseline. Defer, delete and ephemeral keep using the latest
state, since that describes the tables that exist today.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from argparse import Namespace
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, cast

from dbt_ci.connectors import init_storage_connector
from dbt_ci.runners import resolve_dbt_commands, run_dbt_command
from dbt_ci.schema import RunnerConfig
from dbt_ci.utilities.git import GitAdapter

logger = logging.getLogger(__name__)

SHA_PLACEHOLDER = "{sha}"
# Where the baseline manifest is written, inside the dbt project directory so the
# Docker runner's project mount covers it like the default .dbtstate directory
BASELINE_DIR_NAME = ".dbtstate-baseline"
DEFAULT_LOOKBACK = 50


@dataclass
class Baseline:
    """The manifest init compares against, and how it was found."""

    # Directory holding the baseline manifest.json, passed to dbt as --state
    state_dir: str
    # The commit the manifest describes
    sha: str
    source: Literal["archived", "compiled"]
    # The merge base, which the archived manifest may predate on batched deploys
    merge_base: str
    # Commits between the merge base and the archived manifest's commit
    commits_before_merge_base: int = 0

    def describe(self) -> str:
        """Say in one line which manifest the comparison used."""
        if self.source == "compiled":
            return f"the merge base {self.sha[:12]}, compiled for this run"
        if self.commits_before_merge_base:
            return (
                f"the manifest archived for {self.sha[:12]}, "
                f"{self.commits_before_merge_base} commit(s) before the merge base "
                f"{self.merge_base[:12]}"
            )
        return f"the manifest archived for the merge base {self.sha[:12]}"

    def to_dict(self) -> dict[str, Any]:
        """Return the baseline as a JSON-friendly dict for the cache."""
        return {**asdict(self), "description": self.describe()}


def resolve_baseline(args: Namespace) -> Baseline | None:
    """
    Return the merge-base baseline to compare against, or None for the latest state.

    Programmatic callers that don't set compare_to get the latest state; the CLI defaults
    to auto. When no baseline can be used, None is returned and init behaves as before.
    """
    mode = (getattr(args, "compare_to", None) or "latest").lower()
    if mode == "latest":
        return None
    # auto falls back quietly; an explicit merge-base says loudly why it could not
    fallback = logger.info if mode == "auto" else logger.warning

    try:
        git = GitAdapter(args, best_effort=True)
        merge_base = git.merge_base_sha() if git.merge_base_found else None
        head = _head_sha()
    except Exception as e:
        logger.debug(f"Could not use git to find the merge base: {e}")
        merge_base = head = None
    if merge_base is None:
        fallback(
            "Could not find where this branch started (no git history or remote); "
            "comparing against the latest state."
        )
        return None
    if merge_base == head:
        # e.g. a deploy job on main: comparing the branch with itself would find nothing
        fallback(
            "This branch has no commits of its own (e.g. a run on the base branch); "
            "comparing against the latest state."
        )
        return None

    out_dir = Path(getattr(args, "dbt_project_dir", None) or ".") / BASELINE_DIR_NAME
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    archive = archive_template(args)
    if archive:
        history = git.first_parent_history(merge_base, DEFAULT_LOOKBACK)
        found = find_archived_manifest(archive, history)
        if found is not None:
            sha, manifest = found
            write_manifest(out_dir, manifest)
            baseline = Baseline(
                str(out_dir),
                sha,
                "archived",
                merge_base,
                history.index(sha) if sha in history else 0,
            )
            logger.info(f"Comparing against {baseline.describe()}.")
            return baseline
        logger.info(
            f"No manifest kept at {archive} for the merge base or the {len(history) - 1} "
            "commit(s) before it; compiling the merge base instead."
        )

    if getattr(args, "runner", None) == "docker":
        fallback(
            "Compiling the merge base is not supported with the Docker runner, and no "
            "manifest was kept for it next to the state; comparing against the latest state."
        )
        return None

    try:
        compile_merge_base(args, git, merge_base, out_dir)
    except Exception as e:
        fallback(
            f"Compiling the merge base {merge_base[:12]} failed ({e}); comparing against the "
            "latest state."
        )
        return None
    baseline = Baseline(str(out_dir), merge_base, "compiled", merge_base)
    logger.info(f"Comparing against {baseline.describe()}.")
    return baseline


def archive_template(args: Namespace) -> str | None:
    """
    Return where per-commit manifests are kept, with {sha} for the commit, if anywhere.

    finalize keeps them next to the manifest it uploads, so they sit next to the state:
    gs://bucket/dbt-state/manifest.json -> gs://bucket/dbt-state/{sha}/manifest.json.
    """
    state_uri = getattr(args, "state_uri", None)
    if state_uri:
        directory = state_uri.rsplit("/", 1)[0] if state_uri.endswith(".json") else state_uri
        return f"{directory.rstrip('/')}/{SHA_PLACEHOLDER}/manifest.json"
    state = getattr(args, "reference_state", None)
    if state:
        directory = os.path.dirname(state) if state.endswith(".json") else state
        return os.path.join(directory, SHA_PLACEHOLDER, "manifest.json")
    return None


def _head_sha() -> str | None:
    """Return the checked-out commit's SHA, or None outside a git checkout."""
    result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and sha else None


def find_archived_manifest(uri_template: str, history: list[str]) -> tuple[str, Any] | None:
    """
    Return the newest commit in `history` with an archived manifest, and that manifest.

    Remote storage is listed once to see which commits have a manifest, rather than
    trying a download per commit; if listing is not allowed, each commit is tried in
    turn. A local path template is checked file by file.
    """
    if SHA_PLACEHOLDER not in uri_template:
        raise ValueError(
            f"The archive location must contain {SHA_PLACEHOLDER}, got '{uri_template}'."
        )
    if not history:
        return None

    storage = init_storage_connector(uri_template) if "://" in uri_template else None
    if storage is None:
        for sha in history:
            path = uri_template.replace(SHA_PLACEHOLDER, sha)
            path = os.path.join(path, "manifest.json") if os.path.isdir(path) else path
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    return sha, json.load(f)
        return None

    connector, _ = storage
    candidates = history
    try:
        archived = archived_shas(uri_template, connector["list"](prefix_of(uri_template)))
        candidates = [sha for sha in history if sha in archived]
        if not candidates:
            return None
    except Exception as e:
        logger.debug(f"Listing archived manifests failed ({e}); trying each commit in turn.")

    for sha in candidates:
        try:
            return sha, connector["download"](uri_template.replace(SHA_PLACEHOLDER, sha))
        except Exception as e:
            logger.debug(f"No archived manifest for {sha[:12]}: {e}")
    return None


def prefix_of(uri_template: str) -> str:
    """Return the part of a template before {sha}, the prefix to list."""
    return uri_template.split(SHA_PLACEHOLDER, 1)[0]


def archived_shas(uri_template: str, uris: list[str]) -> set[str]:
    """Return the commit SHAs in listed URIs that match the template."""
    pattern = re.compile(
        "^" + re.escape(uri_template).replace(re.escape(SHA_PLACEHOLDER), "([0-9a-f]{40})") + "$"
    )
    return {match.group(1) for uri in uris if (match := pattern.match(uri))}


def write_manifest(out_dir: Path, manifest: Any) -> None:
    """Write a manifest into the baseline state directory."""
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f)


def compile_merge_base(args: Namespace, git: GitAdapter, merge_base: str, out_dir: Path) -> None:
    """
    Build the merge base's manifest in a temporary git worktree with `dbt parse`.

    The reference target and vars are used, as for the reference compile, so the
    baseline is comparable with a production manifest. The worktree is removed again
    whatever happens.
    """
    project_dir = getattr(args, "dbt_project_dir", None) or "."
    project_in_repo = git._project_path_in_repo(project_dir)
    profiles_dir = find_profiles_dir(project_dir, getattr(args, "profiles_dir", None))
    workdir = Path(tempfile.mkdtemp(prefix="dbt-ci-baseline-"))
    worktree = workdir / "checkout"

    _git(["worktree", "add", "--detach", str(worktree), merge_base])
    try:
        baseline_project = worktree / project_in_repo if project_in_repo else worktree
        parse_args = Namespace(
            **{
                **vars(args),
                "dbt_project_dir": str(baseline_project),
                "profiles_dir": profiles_dir,
                "target": getattr(args, "reference_target", None) or getattr(args, "target", None),
                "vars": getattr(args, "reference_vars", None) or getattr(args, "vars", None),
                # Parsing needs neither state nor deferral
                "reference_state": None,
                "defer": False,
            }
        )
        if any(
            (baseline_project / name).is_file() for name in ("packages.yml", "dependencies.yml")
        ):
            _run_dbt(["deps"], parse_args)
        _run_dbt(["parse"], parse_args)
        shutil.copy(baseline_project / "target" / "manifest.json", out_dir / "manifest.json")
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree)], capture_output=True, text=True
        )
        shutil.rmtree(workdir, ignore_errors=True)


def find_profiles_dir(project_dir: str, profiles_dir: str | None) -> str | None:
    """Return the absolute directory dbt would read profiles.yml from for this project."""
    candidates = (
        [Path(profiles_dir)]
        if profiles_dir
        else [Path(project_dir), Path.cwd(), Path.home() / ".dbt"]
    )
    for directory in candidates:
        if (directory / "profiles.yml").is_file():
            return str(directory.resolve())
    return None


def _run_dbt(command: list[str], args: Namespace) -> None:
    """Run a dbt command with the configured runner, raising if it fails."""
    run_dbt_command(
        command_args=resolve_dbt_commands(command, args),
        runner_config=cast(RunnerConfig, args.__dict__),
    )


def _git(command: list[str]) -> None:
    """Run a git command, raising with git's own message if it fails."""
    result = subprocess.run(["git", *command], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(command)} failed")
