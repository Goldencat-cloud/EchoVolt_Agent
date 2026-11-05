"""Render the human-facing report.html.

Data seam: every statistic arrives via [[NUM:...]] tokens resolved from
output/numbers.json. Sections/blocks come from configs/content.json; block
builders are looked up in blocks.BLOCKS (pluggable registry). Layout anatomy
and theme live in configs/template.html.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from . import blocks
from .paths import ASSETS, CONFIGS, OUTPUT

TOKEN = re.compile(r"\[\[([A-Z_]+(?::[^\]]+)?)\]\]")


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    raise SystemExit(2)


def get_path(d, path):
    cur = d
    for part in path.split("."):
        if isinstance(cur, list):
            if not part.isdigit() or int(part) >= len(cur):
                fail(f"numbers.json missing '{path}' - content/data mismatch, refusing to render")
            cur = cur[int(part)]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            fail(f"numbers.json missing '{path}' - content/data mismatch, refusing to render")
    return cur


TABLES = ("aspects", "funnel", "journey", "scope", "ownership", "overview")


class Renderer:
    def __init__(self, n, figs):
        self.n = n
        self.figs = figs

    # ---- shared helpers ----
    def text(self, s: str) -> str:
        def sub(m):
            token = m.group(1)
            if token.startswith("NUM:"):
                return str(get_path(self.n, token[4:]))
            if token == "BUILT_AT":
                return self.n["meta"]["generated_at"]
            fail(f"unknown token '{token}' in content")
        return TOKEN.sub(sub, s)

    def paras(self, s: str) -> str:
        return "".join(f"<p>{escape(p.strip())}</p>" for p in s.split("\n\n") if p.strip())

    # ---- tables (named) ----
    def table(self, name):
        n = self.n
        if name == "overview":
            m = n["meta"]
            rows = [("论坛帖子", m["posts_total"]), ("用户观点表达", m["claims_total"]),
                    ("产品提及", m["mentions_total"]),
                    ("样本时间范围", f"{m['date_min']} 至 {m['date_max']}"),
                    ("体验与风险表达（主分析集）", n["funnel"][2]["claims_s"]),
                    ("引文可定位检查", f"{m['ev_pass']} 通过（{m['ev_rate']}），{m['ev_review']} 待复核")]
            body = "".join(f"<tr><td>{escape(k)}</td><td class='num'>{escape(v)}</td></tr>" for k, v in rows)
            return f"<table><tbody>{body}</tbody></table>"
        if name == "aspects":
            head = ("<tr><th>议题</th><th class='num'>帖数</th><th class='num'>表达</th><th class='num'>正面</th>"
                    "<th class='num'>负面</th><th class='num'>中性</th><th class='num'>其他</th><th class='num'>负面占比</th></tr>")
            body = "".join(
                f"<tr><td>{escape(r['aspect'])}</td><td class='num'>{r['posts']}</td><td class='num'>{r['claims']}</td>"
                f"<td class='num'>{r['positive']}</td><td class='num'>{r['negative']}</td>"
                f"<td class='num'>{r['neutral']}</td><td class='num'>{r['other']}</td>"
                f"<td class='num {'warn' if float(r['negativeShare']) >= 0.30 else ''}'>{r['share_s']}</td></tr>"
                for r in n["aspects"])
            return f"<table>{head}{body}</table>"
        if name == "funnel":
            head = "<tr><th>用户群体</th><th class='num'>帖数</th><th class='num'>表达数</th><th class='num'>相对上一层保留率</th></tr>"
            body = "".join(
                f"<tr><td>{escape(r['name'])}</td><td class='num'>{r['posts_s']}</td>"
                f"<td class='num'>{r['claims_s']}</td><td class='num'>{r['retain'] or '—'}</td></tr>"
                for r in n["funnel"])
            return f"<table>{head}{body}</table>"
        if name == "journey":
            j = n["journey"]
            pairs = [("外观与内饰", "pre_ext", "own_ext"), ("价格与成本", "pre_price", "own_price"),
                     ("空间与舒适性", "pre_comfort", "own_comfort"), ("服务与交付", "pre_svc", "own_svc"),
                     ("续航与能耗", "pre_range", "own_range"), ("智能座舱与车机", "pre_cockpit", "own_cockpit"),
                     ("动力与性能", "pre_power", "own_power"), ("驾驶与操控", "pre_drive", "own_drive")]
            head = ("<tr><th>议题</th><th class='num'>购车前表达</th><th class='num'>购车前负面占比</th>"
                    "<th class='num'>使用阶段表达</th><th class='num'>使用阶段负面占比</th></tr>")
            body = "".join(
                f"<tr><td>{escape(name)}</td><td class='num'>{p['claims']}</td><td class='num'>{p['share_s']}</td>"
                f"<td class='num'>{o['claims']}</td><td class='num'>{o['share_s']}</td></tr>"
                for name, pk, ok in pairs for p, o in [(j[pk], j[ok])])
            return f"<table>{head}{body}</table>"
        if name == "scope":
            head = "<tr><th>车系</th><th class='num'>共提及帖数</th></tr>"
            body = "".join(
                f"<tr><td>{escape(c['brand'])} {escape(c['series'])}</td><td class='num'>{c['posts']}</td></tr>"
                for c in n["scope"]["top"])
            return f"<table>{head}{body}</table>"
        if name == "ownership":
            head = "<tr><th>持有标识</th><th class='num'>帖数</th></tr>"
            body = "".join(
                f"<tr><td>{escape(r['ownership'])}</td><td class='num'>{r['posts']}</td></tr>"
                for r in n["ownership"])
            return f"<table>{head}{body}</table>"
        fail(f"unknown table name '{name}'")

    # ---- block builders (registered in blocks.BLOCKS) ----
    def _b_para(self, b, sid, idx):
        return self.paras(self.text(b["text"]))

    def _b_note(self, b, sid, idx):
        return f"<p class='note'>{escape(self.text(b['text']))}</p>"

    def _b_figure(self, b, sid, idx):
        return self.figure(b["figure"], b["caption"])

    def _b_tabs(self, b, sid, idx):
        btns, panes = [], []
        for i, p in enumerate(b["panes"]):
            pid = f"{sid}-pane-{idx}-{i}"
            btns.append(f"<button data-pane='{pid}' class='{'on' if i == 0 else ''}'>{escape(p['label'])}</button>")
            panes.append(f"<div class='pane {'on' if i == 0 else ''}' id='{pid}'>"
                         f"{self.figure(p['figure'], p['caption'])}</div>")
        return f"<div class='tabs'>{''.join(btns)}</div>{''.join(panes)}"

    def _b_table(self, b, sid, idx):
        return self.table(b["name"])

    def _b_details(self, b, sid, idx):
        return (f"<details><summary>{escape(self.text(b['summary']))}</summary>"
                f"{self.paras(self.text(b['text']))}</details>")

    def _b_cases(self, b, sid, idx):
        aspects = sorted({c["aspect"] for c in self.n["cases"]})
        btns = "<button data-v='' class='on'>全部议题</button>" + "".join(
            f"<button data-v='{escape(a)}'>{escape(a)}</button>" for a in aspects)
        cards = []
        for i, c in enumerate(self.n["cases"], 1):
            sent_cls = {"负面": "b-n", "正面": "b-p"}.get(c["sentiment"], "b-s")
            cards.append(
                f"<div class='case' data-aspect='{escape(c['aspect'])}'>"
                f"<div class='hd'><span><b>{i}. {escape(c['case'])}</b>"
                f"<span class='badge b-a'>{escape(c['aspect'])}</span>"
                f"<span class='badge {sent_cls}'>{escape(c['sentiment'])}</span>"
                f"<span class='badge b-s'>{escape(c['source_status'])}</span></span>"
                f"<span class='meta'>{c['date'][:10]}</span></div>"
                f"<blockquote>{escape(c['quote'])}</blockquote>"
                f"<div class='need'><b>改进假设：</b>{escape(c['need'])}</div>"
                f"<div class='bd'><b>证据边界：</b>{escape(c['boundary'])} · "
                f"<a href='{escape(c['url'])}' target='_blank' rel='noopener'>原帖链接</a></div></div>")
        return f"<div class='filterbar' id='casefilter'>{btns}</div>{''.join(cards)}"

    def _b_recs(self, b, sid, idx):
        out = []
        for it in b["items"]:
            lv = it["level"].lower()
            out.append(
                f"<div class='rec {lv}'><span class='p'>{escape(it['level'])}</span>"
                f"<b>{escape(self.text(it['title']))}</b>"
                f"<div class='ev'><b>依据：</b>{escape(self.text(it['basis']))}</div>"
                f"<div class='bd'><b>边界：</b>{escape(self.text(it['boundary']))}</div></div>")
        return "\n".join(out)

    def _b_conclusion(self, b, sid, idx):
        return f"<div class='concl'>{escape(self.text(b['text']))}</div>"

    def render_blocks(self, sid, block_list):
        out = []
        for idx, b in enumerate(block_list):
            method = blocks.BLOCKS.get(b["type"])
            if not method:
                fail(f"unknown block type '{b['type']}' in section {sid} - "
                     f"registered types: {sorted(blocks.BLOCKS)}")
            out.append(getattr(self, method)(b, sid, idx))
        return "\n".join(out)

    # ---- composites ----
    def figure(self, fig, caption):
        if fig not in self.figs:
            fail(f"figure missing: {fig} - run build_report.py first")
        return f"<figure>{self.figs[fig]}<figcaption>{escape(self.text(caption))}</figcaption></figure>"

    def section(self, s):
        blocks_html = self.render_blocks(s["id"], s["blocks"])
        return (f"<section id='{escape(s['id'])}'><h2>{escape(self.text(s['title']))}</h2>"
                + (f"<p class='lead'>{escape(self.text(s['lead']))}</p>" if s.get("lead") else "")
                + blocks_html + "</section>")

    def finding(self, order, f):
        html = (f"<section id='{escape(f['id'])}'><h2><span class='no'>{order}</span>"
                f"{escape(self.text(f['title']))}</h2>"
                f"<div class='finding'><span class='fl'>发现</span>"
                f"{escape(self.text(f['statement']))}</div>"
                + self.render_blocks(f["id"], f["blocks"]))
        if f.get("implication"):
            html += (f"<div class='impl'><span class='fl'>研究含义</span>"
                     f"{escape(self.text(f['implication']))}</div>")
        return html + "</section>"

    # ---- assembly ----
    def build(self, content):
        c = content["cover"]
        cards = "".join(f"<div class='stat'><b>{self.text(x['value'])}</b><span>{escape(x['label'])}</span></div>"
                        for x in c["cards"])
        cover = (f"<div class='cover'><div class='rule'></div>"
                 f"<div class='kicker'>{escape(self.text(c['kicker']))}</div>"
                 f"<h1>{escape(self.text(c['title']))}</h1>"
                 f"<div class='sub'>{escape(self.text(c['subtitle']))}</div>"
                 f"<div class='chips'>{escape(self.text(c['chips']))}</div>"
                 f"<div class='statstrip'>{cards}</div></div>")

        summary = "".join(
            f"<div class='concl'><span class='sid'>{escape(it['id'])}</span>"
            f"{escape(self.text(it['text']))}</div>" for it in content["summary"])
        summary_sec = (f"<section id='summary-block'><h2>核心发现</h2>{summary}"
                       f"<p class='note'>各项发现的证据与含义见下文对应章节；口径与使用边界见附录。</p></section>")

        method_sec = self.section(content["methodology"])
        findings = "\n".join(self.finding(i, f) for i, f in enumerate(content["findings"], 1))
        rec_sec = self.section(content["recommendations"])
        appendix = "".join(
            f"<details><summary>{escape(self.text(a['summary']))}</summary>{self.paras(self.text(a['text']))}</details>"
            for a in content["appendix"])
        appendix_sec = f"<section id='appendix'><h2>附录</h2>{appendix}</section>"

        toc = ("<a href='#s-method'>研究方法与数据</a>"
               + "".join(f"<a href='#{escape(f['id'])}'>{escape(f['id'])} {escape(self.text(f['toc']))}</a>"
                         for f in content["findings"])
               + "<a href='#s-rec'>建议与优先级</a><a href='#appendix'>附录</a>")

        return {"PAGE_TITLE": escape(self.text(c["title"])), "NAV_BRAND": "SU7 用户声音分析",
                "COVER": cover, "SUMMARY": summary_sec, "SECTIONS": method_sec + findings + rec_sec,
                "APPENDIX": appendix_sec, "TOC": toc,
                "FOOTER": (f"由构建脚本从冻结数据自动生成，数字经一致性校验 · 与机器可读知识库 report.md 同源 · "
                           f"生成时间 {self.n['meta']['generated_at']}")}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    for f in (OUTPUT / "numbers.json", OUTPUT / "data-version.json",
              CONFIGS / "content.json", CONFIGS / "template.html"):
        if not f.is_file():
            fail(f"{f.name} missing at {f.parent} - run build_report.py first")
    n = json.loads((OUTPUT / "numbers.json").read_text(encoding="utf-8"))
    manifest = json.loads((OUTPUT / "data-version.json").read_text(encoding="utf-8"))
    figs = {}
    for fig in manifest["figures"]:
        p = ASSETS / fig
        if not p.is_file():
            fail(f"figure missing: output/assets/{fig} - run build_report.py first")
        figs[fig] = p.read_text(encoding="utf-8")
    content = json.loads((CONFIGS / "content.json").read_text(encoding="utf-8"))

    parts = Renderer(n, figs).build(content)
    html = (CONFIGS / "template.html").read_text(encoding="utf-8")

    missing = []
    def sub(m):
        token = m.group(1)
        if token not in parts:
            missing.append(token)
            return token
        return parts[token]
    html = TOKEN.sub(sub, html)
    if missing:
        fail(f"template tokens not produced by renderer: {sorted(set(missing))}")
    leftover = TOKEN.findall(html)
    if leftover:
        fail(f"unresolved tokens after render: {sorted(set(leftover))}")
    (OUTPUT / "report.html").write_text(html, encoding="utf-8")
    print(json.dumps({"ok": True, "output": "output/report.html",
                      "findings": len(content["findings"]),
                      "figures": len(figs), "cases": n["cases_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
