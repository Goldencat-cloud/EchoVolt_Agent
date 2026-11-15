"""技能目录保护：运行期不可改写技能定义，且 profile 声明的技能必须存在。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_engine
from kernel.profile import DELIVERABLE, INTERACTIVE

# 私有但稳定：权限判定是框架唯一的“规则 → 决策”入口，直接测它能覆盖真实行为
from deepagents.middleware.filesystem import _check_fs_permission


class SkillWriteGuardTests(unittest.TestCase):
    """backend 的 root 就是技能目录，写权限必须收窄到技能文件之外。"""

    def test_skill_files_are_write_denied(self):
        rules = agent_engine.skill_permissions()
        for path in ("/deep-analysis/SKILL.md",
                     "/execute-plan/SKILL.md",
                     "/execute-plan/reference/evidence.md",
                     "/report-authoring/reference/caliber.md"):
            self.assertEqual(_check_fs_permission(rules, "write", path), "deny", path)

    def test_read_is_still_allowed(self):
        rules = agent_engine.skill_permissions()
        for path in ("/execute-plan/SKILL.md",
                     "/execute-plan/reference/semantic-query.md"):
            self.assertEqual(_check_fs_permission(rules, "read", path), "allow", path)

    def test_non_skill_paths_remain_writable(self):
        """摘要中间件等工作区文件仍要可写，否则技能保护会误伤运行。"""
        rules = agent_engine.skill_permissions()
        self.assertEqual(_check_fs_permission(rules, "write", "/scratch/notes.md"), "allow")


class DeclaredSkillsTests(unittest.TestCase):
    def test_deliverable_skills_exist_on_disk(self):
        agent_engine.assert_skills_exist(DELIVERABLE.skills)

    def test_interactive_declares_no_skills(self):
        self.assertEqual(INTERACTIVE.skills, ())
        agent_engine.assert_skills_exist(INTERACTIVE.skills)

    def test_unknown_skill_is_rejected(self):
        with self.assertRaises(ValueError):
            agent_engine.assert_skills_exist(("no-such-skill",))

    def test_renamed_skill_is_accepted(self):
        """改名后的 execute-plan 应被视为合法技能。"""
        agent_engine.assert_skills_exist(("execute-plan",))


if __name__ == "__main__":
    unittest.main()
