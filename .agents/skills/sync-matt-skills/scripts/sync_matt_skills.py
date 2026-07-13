#!/usr/bin/env python3
"""Safely mirror skills declared by mattpocock/skills into a project."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence


SOURCE = "mattpocock/skills"
SOURCE_TYPE = "github"
SOURCE_URL = "https://github.com/mattpocock/skills.git"
PLUGIN_MANIFEST = ".claude-plugin/plugin.json"
SKILLS_CLI_VERSION = "1.5.16"


class SyncError(RuntimeError):
    """Raised when a safe sync cannot be completed."""


@dataclass(frozen=True)
class Conflict:
    name: str
    reason: str
    forceable: bool


@dataclass(frozen=True)
class SyncPlan:
    added: List[str]
    updated: List[str]
    removed: List[str]
    conflicts: List[Conflict]

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.removed)


def read_lock(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"version": 1, "skills": {}}
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SyncError(f"Cannot read {path}: {error}") from error
    if not isinstance(lock, dict) or not isinstance(lock.get("skills"), dict):
        raise SyncError(f"Invalid skills lock: {path}")
    return lock


def managed_entries(lock: Mapping[str, object]) -> Dict[str, Dict[str, object]]:
    skills = lock.get("skills", {})
    if not isinstance(skills, dict):
        return {}
    return {
        name: entry
        for name, entry in skills.items()
        if isinstance(name, str)
        and isinstance(entry, dict)
        and entry.get("source") == SOURCE
        and entry.get("sourceType") == SOURCE_TYPE
    }


def folder_hash(path: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(item for item in path.rglob("*") if item.is_file())
    for item in files:
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(item.read_bytes())
    return digest.hexdigest()


def has_local_changes(path: Path, entry: Mapping[str, object]) -> bool:
    expected_hash = entry.get("computedHash")
    return path.exists() and (
        not isinstance(expected_hash, str) or folder_hash(path) != expected_hash
    )


def build_plan(
    project_skills: Path,
    local_lock: Mapping[str, object],
    upstream_lock: Mapping[str, object],
) -> SyncPlan:
    local = managed_entries(local_lock)
    upstream = managed_entries(upstream_lock)
    local_names = set(local)
    upstream_names = set(upstream)
    added = sorted(upstream_names - local_names)
    removed = sorted(local_names - upstream_names)
    updated = sorted(
        name
        for name in local_names & upstream_names
        if local[name].get("computedHash") != upstream[name].get("computedHash")
    )

    conflicts: List[Conflict] = []
    for name in added:
        target = project_skills / name
        if target.exists() and any(target.iterdir()):
            conflicts.append(Conflict(name, "unmanaged skill has the same name", False))
    for name in updated + removed:
        if has_local_changes(project_skills / name, local[name]):
            conflicts.append(Conflict(name, "managed skill has local changes", True))
    return SyncPlan(added, updated, removed, conflicts)


def install_upstream(destination: Path) -> None:
    command = [
        "npx",
        "-y",
        f"skills@{SKILLS_CLI_VERSION}",
        "add",
        SOURCE,
        "--skill",
        "*",
        "--agent",
        "codex",
        "claude-code",
        "--yes",
    ]
    print(f"Fetching {SOURCE} with skills CLI {SKILLS_CLI_VERSION}...")
    try:
        subprocess.run(
            command,
            cwd=destination,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as error:
        raise SyncError("npx is required but was not found") from error
    except subprocess.CalledProcessError as error:
        details = error.stderr.strip() if error.stderr else "no error output"
        raise SyncError(
            f"skills CLI failed with exit code {error.returncode}: {details}"
        ) from error


def read_declared_skill_names() -> List[str]:
    with tempfile.TemporaryDirectory(prefix="matt-skills-source-") as directory:
        checkout = Path(directory) / "repository"
        try:
            subprocess.run(
                ["git", "clone", "--quiet", "--depth", "1", SOURCE_URL, str(checkout)],
                check=True,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as error:
            raise SyncError("git is required but was not found") from error
        except subprocess.CalledProcessError as error:
            details = error.stderr.strip() if error.stderr else "no error output"
            raise SyncError(f"Cannot fetch plugin manifest: {details}") from error

        manifest_path = checkout / PLUGIN_MANIFEST
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SyncError(f"Cannot read plugin manifest: {error}") from error

    skills = manifest.get("skills") if isinstance(manifest, dict) else None
    if not isinstance(skills, list) or not all(isinstance(item, str) for item in skills):
        raise SyncError("Plugin manifest has an invalid skills list")
    names = [Path(item).name for item in skills]
    if len(names) != len(set(names)):
        raise SyncError("Plugin manifest declares duplicate skill names")
    return names


def filter_upstream_lock(
    upstream_lock: Mapping[str, object], declared_names: Sequence[str]
) -> Dict[str, object]:
    upstream = managed_entries(upstream_lock)
    missing = sorted(set(declared_names) - set(upstream))
    if missing:
        raise SyncError(f"Declared skills missing from CLI output: {', '.join(missing)}")
    return {
        "version": upstream_lock.get("version", 1),
        "skills": {name: upstream[name] for name in declared_names},
    }


def validate_staging(staging_root: Path, upstream_lock: Mapping[str, object]) -> None:
    entries = managed_entries(upstream_lock)
    if not entries:
        raise SyncError(f"No {SOURCE} skills found in staged lock")
    staged_skills = staging_root / ".agents" / "skills"
    missing = sorted(name for name in entries if not (staged_skills / name).is_dir())
    if missing:
        raise SyncError(f"Staged skills are missing: {', '.join(missing)}")


def merged_lock(
    local_lock: Mapping[str, object], upstream_lock: Mapping[str, object]
) -> Dict[str, object]:
    local_skills = local_lock.get("skills", {})
    preserved = {
        name: entry
        for name, entry in local_skills.items()
        if isinstance(local_skills, dict)
        and not (
            isinstance(entry, dict)
            and entry.get("source") == SOURCE
            and entry.get("sourceType") == SOURCE_TYPE
        )
    }
    preserved.update(managed_entries(upstream_lock))
    return {
        "version": max(
            int(local_lock.get("version", 1)), int(upstream_lock.get("version", 1))
        ),
        "skills": dict(sorted(preserved.items())),
    }


def write_lock_atomic(path: Path, lock: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    os.replace(str(temporary), str(path))


def apply_plan(
    project_root: Path,
    staging_root: Path,
    plan: SyncPlan,
    local_lock: Mapping[str, object],
    upstream_lock: Mapping[str, object],
    force: bool = False,
) -> None:
    hard_conflicts = [conflict for conflict in plan.conflicts if not conflict.forceable]
    soft_conflicts = [conflict for conflict in plan.conflicts if conflict.forceable]
    if hard_conflicts or (soft_conflicts and not force):
        raise SyncError("Conflicts must be resolved before applying the sync")

    project_skills = project_root / ".agents" / "skills"
    staged_skills = staging_root / ".agents" / "skills"
    lock_path = project_root / "skills-lock.json"
    project_skills.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="matt-skills-backup-") as backup_dir:
        backup_root = Path(backup_dir)
        skills_backup = backup_root / "skills"
        lock_backup = backup_root / "skills-lock.json"
        skills_existed = project_skills.exists()
        lock_existed = lock_path.exists()
        if skills_existed:
            shutil.copytree(project_skills, skills_backup, symlinks=True)
        if lock_existed:
            shutil.copy2(lock_path, lock_backup)

        try:
            project_skills.mkdir(parents=True, exist_ok=True)
            for name in plan.removed + plan.updated:
                target = project_skills / name
                if target.exists():
                    shutil.rmtree(target)
            for name in plan.added + plan.updated:
                target = project_skills / name
                if target.exists():
                    target.rmdir()
                shutil.copytree(staged_skills / name, project_skills / name)
            write_lock_atomic(lock_path, merged_lock(local_lock, upstream_lock))
        except Exception as error:
            if project_skills.exists():
                shutil.rmtree(project_skills)
            if skills_existed:
                shutil.copytree(skills_backup, project_skills, symlinks=True)
            if lock_path.exists():
                lock_path.unlink()
            if lock_existed:
                shutil.copy2(lock_backup, lock_path)
            raise SyncError(f"Sync failed and was rolled back: {error}") from error


def print_plan(plan: SyncPlan) -> None:
    groups: Iterable[tuple[str, Sequence[str]]] = (
        ("Add", plan.added),
        ("Update", plan.updated),
        ("Remove", plan.removed),
    )
    for label, names in groups:
        print(f"{label} ({len(names)}): {', '.join(names) if names else '-'}")
    if plan.conflicts:
        print(f"Conflicts ({len(plan.conflicts)}):")
        for conflict in plan.conflicts:
            suffix = "can use --force" if conflict.forceable else "manual action required"
            print(f"  - {conflict.name}: {conflict.reason} ({suffix})")
    else:
        print("Conflicts (0): -")


def find_project_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "skills-lock.json").exists() or (path / ".agents").is_dir():
            return path
    raise SyncError("Run this command inside a project with .agents or skills-lock.json")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply the displayed changes")
    parser.add_argument(
        "--force", action="store_true", help="Overwrite modified managed skills"
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.force and not args.apply:
        print("error: --force requires --apply", file=sys.stderr)
        return 2
    try:
        project_root = find_project_root(Path.cwd().resolve())
        local_lock = read_lock(project_root / "skills-lock.json")
        with tempfile.TemporaryDirectory(prefix="matt-skills-staging-") as directory:
            staging_root = Path(directory)
            declared_names = read_declared_skill_names()
            install_upstream(staging_root)
            upstream_lock = filter_upstream_lock(
                read_lock(staging_root / "skills-lock.json"), declared_names
            )
            validate_staging(staging_root, upstream_lock)
            plan = build_plan(project_root / ".agents" / "skills", local_lock, upstream_lock)
            print_plan(plan)
            if not args.apply:
                print("Preview only. Run again with --apply to sync.")
                return 1 if plan.conflicts else 0
            apply_plan(project_root, staging_root, plan, local_lock, upstream_lock, args.force)
            print("Sync complete." if plan.changed else "Already in sync.")
            return 0
    except SyncError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
