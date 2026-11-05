"""内核的依赖方向：只允许依赖 kernel 自身与标准库。

回归背景：`kernel/builder.py` 曾反向 import `agent_engine` 与 `agent_tools`，
使"内核"必须随外层一起升级。现在外部能力经 `AgentRuntime` 注入。
"""
import ast
import sys
import unittest
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))

# 外层实现：内核不得感知其中任何一个。
OUTER_MODULES = {
    "agent_engine", "agent_tools", "app", "jobs", "sandbox",
    "report_session", "report_publisher", "report_gate", "report_source",
    "research", "task_brief", "verifier", "clarify", "integrations",
}


def imported_roots(source: str) -> set[str]:
    """源码中所有 import（含函数体内）的顶层包名。"""
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


class KernelBoundaryTests(unittest.TestCase):
    def test_parser_sees_imports_inside_functions(self):
        """守卫本身要能发现延迟导入，否则规则形同虚设。"""
        source = "def build():\n    import agent_tools\n"
        self.assertEqual(imported_roots(source), {"agent_tools"})

    def test_kernel_does_not_import_outer_layers(self):
        offenders = {}
        for path in sorted((SERVICE_DIR / "kernel").glob("*.py")):
            leaked = imported_roots(path.read_text(encoding="utf-8")) & OUTER_MODULES
            if leaked:
                offenders[path.name] = sorted(leaked)
        self.assertEqual(offenders, {})


if __name__ == "__main__":
    unittest.main()
