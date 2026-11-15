"""生成内核等价性 fixture（一次性脚本，产物已提交到 fixtures/kernel/）。

运行：python -m tests.make_kernel_fixtures
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests import kernel_fixture as kf  # noqa: E402


def _row(aspect: str, *, negative_share: float, negative: int, claim_id: str | None = None,
         warnings: list[str] | None = None) -> dict:
    row = {"aspect": aspect, "negative_share": negative_share, "negative": negative,
           "total_claims": negative * 4}
    if claim_id:
        row["claim_id"] = claim_id
        row["url"] = f"https://example.invalid/{claim_id}"
    result = {"rows": [row]}
    if warnings:
        result["warnings"] = warnings
    return {"kind": "method", "aspect": aspect, "method": "negative_share_by_aspect",
            "result": result}


def _overview(aspects: int, *, warnings: list[str] | None = None) -> dict:
    rows = [{"aspect": f"议题{i}", "total_claims": 100 - i * 7, "negative": 10 + i}
            for i in range(1, aspects + 1)]
    result = {"rows": rows}
    if warnings:
        result["warnings"] = warnings
    return {"kind": "overview", "result": result}


def _evidence(aspect: str, claim_ids: list[str], *, via: str = "data") -> dict:
    items = [{"claim_id": cid, "aspect": aspect, "sentiment": "negative",
              "url": f"https://example.invalid/{cid}", "date": "2026-08-01",
              "title": f"观点 {cid}"} for cid in claim_ids]
    key = "rows" if via == "rows" else "data"
    return {"kind": "evidence", "aspect": aspect, "result": {key: items}}


ASPECTS = ["可靠性", "空间与舒适性", "充电", "智能化", "外观与内饰"]

CASES: list[tuple[str, str, list[dict], str, str]] = [
    ("case-01", "你们能做什么？", [], "我可以基于冻结快照回答关于可靠性与空间的统计问题。", "零工具直答"),
    ("case-02", "可靠性怎么样？", [_row(ASPECTS[0], negative_share=0.42, negative=21)],
     "可靠性方面负面占比约 42%，共 21 条负面声明。", "单方法单行"),
    ("case-03", "空间与舒适性有哪些负向体验？",
     [_row(ASPECTS[1], negative_share=0.31, negative=13, claim_id="c-1001")],
     "空间与舒适性负面占比 31%，例如后排坐垫偏短[c-1001]。", "方法行含 claim_id"),
    ("case-04", "充电呢？", [_row(ASPECTS[2], negative_share=0.27, negative=9)],
     "充电负面占比 27%，主要涉及排队与功率衰减。", "单方法"),
    ("case-05", "给我说一下整体分布", [_overview(5)],
     "五个议题的声明量分别为 100、93、86、79、72 条。", "overview 多行"),
    ("case-06", "可靠性和空间哪个负面更多？",
     [_row(ASPECTS[0], negative_share=0.42, negative=21),
      _row(ASPECTS[1], negative_share=0.31, negative=13)],
     "可靠性负面占比 42%，高于空间的 31%。", "两个方法步骤"),
    ("case-07", "有没有原文可以看？",
     [_row(ASPECTS[0], negative_share=0.42, negative=21, claim_id="c-2001"),
      _evidence(ASPECTS[0], ["c-2001", "c-2002"])],
     "可以，例如 c-2001 与 c-2002 两条原文。", "方法+证据步骤"),
    ("case-08", "证据多一点", [_evidence(ASPECTS[3], [f"c-30{i}" for i in range(1, 6)])],
     "智能化方面共有 5 条可用证据。", "仅证据步骤"),
    ("case-09", "可靠性负面占比大概多少？",
     [_row(ASPECTS[0], negative_share=0.42, negative=21, warnings=["样本量偏低"])],
     "约 42%（样本量偏低，仅供参考）。", "带 warning"),
    ("case-10", "再说说外观", [_row(ASPECTS[4], negative_share=0.18, negative=6)],
     "外观与内饰负面占比 18%。", "第五个议题"),
    ("case-11", "五个议题的负面占比", [_overview(5)] + [_row(a, negative_share=0.2 + i * 0.03,
                                                          negative=10 + i)
                                                         for i, a in enumerate(ASPECTS)],
     "五议题负面占比在 20% 到 32% 之间。", "overview + 五个方法步骤"),
    ("case-12", "重复证据要去重吗？",
     [_evidence(ASPECTS[1], ["c-4001", "c-4002"]),
      _evidence(ASPECTS[1], ["c-4002", "c-4003"])],
     "证据按 claim_id 去重后共 3 条。", "证据重复去重"),
    ("case-13", "方法行也带 claim_id 时算什么？",
     [_row(ASPECTS[0], negative_share=0.42, negative=21, claim_id="c-5001"),
      _evidence(ASPECTS[0], ["c-5001", "c-5002"])],
     "方法行与证据行合并去重后共 2 条。", "跨步骤 claim 去重"),
    ("case-14", "空结果怎么处理？", [{"kind": "method", "aspect": ASPECTS[0],
                                       "result": {"rows": []}}],
     "该议题没有可用行。", "空 rows"),
    ("case-15", "结果结构异常时呢？", [{"kind": "method", "aspect": ASPECTS[0], "result": None}],
     "该步骤结果结构异常，已跳过。", "result 非映射"),
    ("case-16", "确认，谢谢", [], "不客气，需要数据时随时说。", "纯寒暄"),
    ("case-17", "可靠性 21 条负面是怎么算的？",
     [_row(ASPECTS[0], negative_share=0.42, negative=21)],
     "21 条负面声明除以 50 条总声明，得到 42%。", "溯源式追问"),
    ("case-18", "空间和充电一起看", [_row(ASPECTS[1], negative_share=0.31, negative=13),
                                     _row(ASPECTS[2], negative_share=0.27, negative=9)],
     "空间 31%、充电 27%，空间更高。", "跨议题比较"),
    ("case-19", "给我一份清单", [_evidence(ASPECTS[2], ["c-6001", "c-6002", "c-6003"], via="rows")],
     "充电方面共 3 条证据。", "证据走 rows 字段"),
    ("case-20", "为什么没有智能化数据？",
     [_overview(3, warnings=["智能化议题数据缺失"])],
     "智能化议题本次缺失（数据缺失）。", "overview 带 warning"),
]


def main() -> int:
    written = 0
    for case_id, question, steps, final_text, note in CASES:
        fixture = kf.record(case_id, question, steps, final_text, note=note)
        kf.save(fixture)
        written += 1
    print(f"written {written} fixtures -> {kf.FIXTURE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
