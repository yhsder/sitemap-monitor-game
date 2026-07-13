import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sync_matt_skills import (  # noqa: E402
    SOURCE,
    SOURCE_TYPE,
    SyncError,
    apply_plan,
    build_plan,
    folder_hash,
    merged_lock,
    validate_staging,
)


def write_skill(root: Path, name: str, content: str) -> Path:
    skill = root / ".agents" / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(content, encoding="utf-8")
    return skill


def entry(path: Path, source: str = SOURCE) -> dict:
    return {
        "source": source,
        "sourceType": SOURCE_TYPE,
        "skillPath": f"skills/{path.name}/SKILL.md",
        "computedHash": folder_hash(path),
    }


def lock(skills: dict) -> dict:
    return {"version": 1, "skills": skills}


class SyncMattSkillsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.staging = self.root / "staging"
        self.project.mkdir()
        self.staging.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_build_plan_detects_add_update_and_remove(self):
        old = write_skill(self.project, "old", "old")
        changed = write_skill(self.project, "changed", "before")
        local = lock({"old": entry(old), "changed": entry(changed)})
        new = write_skill(self.staging, "new", "new")
        staged_changed = write_skill(self.staging, "changed", "after")
        upstream = lock({"new": entry(new), "changed": entry(staged_changed)})

        plan = build_plan(self.project / ".agents" / "skills", local, upstream)

        self.assertEqual(plan.added, ["new"])
        self.assertEqual(plan.updated, ["changed"])
        self.assertEqual(plan.removed, ["old"])
        self.assertEqual(plan.conflicts, [])

    def test_modified_managed_skill_requires_force(self):
        local_skill = write_skill(self.project, "changed", "before")
        local = lock({"changed": entry(local_skill)})
        (local_skill / "SKILL.md").write_text("locally edited", encoding="utf-8")
        staged = write_skill(self.staging, "changed", "upstream edit")
        upstream = lock({"changed": entry(staged)})

        plan = build_plan(self.project / ".agents" / "skills", local, upstream)

        self.assertEqual(len(plan.conflicts), 1)
        self.assertTrue(plan.conflicts[0].forceable)
        with self.assertRaises(SyncError):
            apply_plan(self.project, self.staging, plan, local, upstream)
        apply_plan(self.project, self.staging, plan, local, upstream, force=True)
        self.assertEqual(
            (local_skill / "SKILL.md").read_text(encoding="utf-8"), "upstream edit"
        )

    def test_unmanaged_name_collision_is_never_forceable(self):
        write_skill(self.project, "new", "private")
        staged = write_skill(self.staging, "new", "upstream")
        upstream = lock({"new": entry(staged)})

        plan = build_plan(self.project / ".agents" / "skills", lock({}), upstream)

        self.assertFalse(plan.conflicts[0].forceable)
        with self.assertRaises(SyncError):
            apply_plan(self.project, self.staging, plan, lock({}), upstream, force=True)

    def test_empty_unmanaged_directory_can_be_replaced(self):
        empty = self.project / ".agents" / "skills" / "new"
        empty.mkdir(parents=True)
        staged = write_skill(self.staging, "new", "upstream")
        upstream = lock({"new": entry(staged)})

        plan = build_plan(self.project / ".agents" / "skills", lock({}), upstream)

        self.assertEqual(plan.conflicts, [])
        apply_plan(self.project, self.staging, plan, lock({}), upstream)
        self.assertEqual((empty / "SKILL.md").read_text(encoding="utf-8"), "upstream")

    def test_other_sources_are_preserved(self):
        local = lock({"private": {"source": "owner/private", "sourceType": "github"}})
        staged = write_skill(self.staging, "new", "upstream")
        upstream = lock({"new": entry(staged)})

        result = merged_lock(local, upstream)

        self.assertEqual(result["skills"]["private"]["source"], "owner/private")
        self.assertIn("new", result["skills"])

    def test_missing_managed_directory_can_be_repaired(self):
        local = lock(
            {
                "missing": {
                    "source": SOURCE,
                    "sourceType": SOURCE_TYPE,
                    "computedHash": "old",
                }
            }
        )
        staged = write_skill(self.staging, "missing", "restored")
        upstream = lock({"missing": entry(staged)})

        plan = build_plan(self.project / ".agents" / "skills", local, upstream)

        self.assertEqual(plan.updated, ["missing"])
        self.assertEqual(plan.conflicts, [])

    def test_invalid_staging_is_rejected(self):
        with self.assertRaises(SyncError):
            validate_staging(self.staging, lock({}))

        upstream = lock(
            {
                "missing": {
                    "source": SOURCE,
                    "sourceType": SOURCE_TYPE,
                    "computedHash": "hash",
                }
            }
        )
        with self.assertRaises(SyncError):
            validate_staging(self.staging, upstream)

    def test_apply_rolls_back_files_and_lock_on_failure(self):
        old = write_skill(self.project, "old", "old")
        local = lock({"old": entry(old)})
        lock_path = self.project / "skills-lock.json"
        lock_path.write_text(json.dumps(local), encoding="utf-8")
        new = write_skill(self.staging, "new", "new")
        upstream = lock({"new": entry(new)})
        plan = build_plan(self.project / ".agents" / "skills", local, upstream)

        with mock.patch(
            "sync_matt_skills.write_lock_atomic", side_effect=OSError("boom")
        ):
            with self.assertRaises(SyncError):
                apply_plan(self.project, self.staging, plan, local, upstream)

        self.assertTrue((self.project / ".agents" / "skills" / "old").exists())
        self.assertFalse((self.project / ".agents" / "skills" / "new").exists())
        self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8")), local)


if __name__ == "__main__":
    unittest.main()
