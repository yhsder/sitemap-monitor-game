---
name: sync-matt-skills
description: Safely preview and apply a complete local mirror of skills declared by mattpocock/skills, including upstream additions, updates, and deletions. Use when a project needs to synchronize its installed mattpocock/skills collection while protecting local modifications and unrelated skills.
---

Run the bundled `scripts/sync_matt_skills.py` from the target project root. Resolve the script
relative to this SKILL.md so the skill works after moving its entire directory to another project.

1. Run `python3 <skill-dir>/scripts/sync_matt_skills.py` and report the preview.
2. Run again with `--apply` only after the user asks to apply the displayed changes.
3. Add `--force` only after the user explicitly approves overwriting modified managed skills.
4. Never work around an unmanaged skill name collision. Ask the user to rename or remove it.

The script requires Node.js with `npx`, stages the pinned skills CLI in a temporary directory,
and rolls back project files if applying the mirror fails.
