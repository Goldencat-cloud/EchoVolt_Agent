"""把 corpus 重排成「术语 / 政策」两类，并统一文件命名。

一次性脚本：只搬文件、不改内容；已存在的目标不会被覆盖。
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpus"
TERMS = CORPUS / "术语"
POLICY = CORPUS / "政策"
ATTACH = POLICY / "附件"

# 术语标准：源文件名 -> 可读文件名
TERM_RENAME = {
    "GBT+19596-2017.pdf": "GB-T 19596-2017 电动汽车术语.pdf",
    "GBT+29317-2021.pdf": "GB-T 29317-2021 电动汽车充换电设施术语.pdf",
    "GBT+3730.1-2022.pdf": "GB-T 3730.1-2022 汽车挂车及汽车列车术语 第1部分 类型.pdf",
    "GBT+38146.1-2019.pdf": "GB-T 38146.1-2019 中国汽车行驶工况 第1部分 轻型汽车.pdf",
    "GBT+39263-2020.pdf": "GB-T 39263-2020 道路车辆 先进驾驶辅助系统术语及定义.pdf",
    "GBT+40032-2021.pdf": "GB-T 40032-2021 电动汽车换电安全要求.pdf",
    "GBT+40429-2021.pdf": "GB-T 40429-2021 汽车驾驶自动化分级.pdf",
    "GBT+5624-2019.pdf": "GB-T 5624-2019 汽车维修术语.pdf",
    "GB-T 44373-2024 智能网联汽车 术语和定义.pdf": "GB-T 44373-2024 智能网联汽车 术语和定义.pdf",
}

# 强制国标属于合规要求，归政策
FORCED_GB = [
    "GB 18384-2025 电动汽车安全要求.pdf",
    "GB 36980.1-2025 电动汽车能量消耗量限值 第1部分 乘用车.pdf",
    "GB 38031-2025 电动汽车用动力蓄电池安全要求.pdf",
    "GB 44496-2024 汽车软件升级通用技术要求.pdf",
]

moved = 0
for src_dir, pattern, dst_dir, rename in (
    (CORPUS / "standards", "*.pdf", TERMS, TERM_RENAME),
    (CORPUS / "standards", "*.pdf", POLICY, {n: n for n in FORCED_GB}),
    (CORPUS / "policies", "*.md", POLICY, {}),
    (CORPUS / "policies", "*.json", POLICY, {}),
    (CORPUS / "sources", "*.md", POLICY, {}),
    (CORPUS / "attachments", "*.*", ATTACH, {}),
):
    dst_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(src_dir.glob(pattern)) if src_dir.exists() else []:
        name = rename.get(path.name, path.name)
        if path.name not in rename and rename:
            continue  # 不在映射表里的不搬
        target = dst_dir / name
        if target.exists():
            print(f"[skip] 目标已存在: {target.relative_to(CORPUS)}")
            continue
        shutil.move(str(path), str(target))
        moved += 1
        print(f"[move] {path.name}  ->  {target.relative_to(CORPUS)}")

# 清理空目录与转换日志
for stale in ("standards", "policies", "sources", "attachments", "_text"):
    d = CORPUS / stale
    if d.exists():
        left = [p for p in d.rglob("*") if p.is_file()]
        if not left:
            shutil.rmtree(d)
            print(f"[rm] 空目录 {stale}/")
        else:
            print(f"[keep] {stale}/ 仍有 {len(left)} 个文件")

print(f"\n共移动 {moved} 个文件")
