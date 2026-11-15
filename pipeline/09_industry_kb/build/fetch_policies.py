"""抓取政策原文页，转 Markdown 落盘，并列出页面附件。

只用标准库 + requests，不引入解析依赖。用法：
    python build/fetch_policies.py
输出：
    corpus/policies/<doc_id>.md      带 front-matter 的正文
    corpus/policies/_attachments.json 各页附件清单
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "corpus" / "policies"

SKIP_TAGS = {"script", "style", "nav", "header", "footer", "noscript", "iframe"}
BLOCK_TAGS = {"p", "div", "br", "li", "tr", "section", "article", "table"}
HEADING_TAGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####"}
ATTACH_EXT = (".doc", ".docx", ".pdf", ".xls", ".xlsx", ".wps", ".zip", ".rar")

DOCS = [
    {
        "doc_id": "2023购置税减免公告",
        "filename": "2023年-购置税减免延续和优化公告.md",
        "kind": "document",
        "url": "https://www.gov.cn/zhengce/zhengceku/202306/content_6887734.htm",
        "publisher": "财政部、税务总局、工业和信息化部",
        "doc_number": "财政部 税务总局 工业和信息化部公告2023年第10号",
        "publish_date": "2023-06-19",
        "status": "现行",
    },
    {
        "doc_id": "2025购置税技术要求",
        "filename": "2025年-购置税减免产品技术要求公告.md",
        "kind": "document",
        "url": "https://www.gov.cn/zhengce/zhengceku/202510/content_7053638.htm",
        "publisher": "工业和信息化部、财政部、税务总局",
        "doc_number": "工业和信息化部 财政部 税务总局公告2025年第24号",
        "publish_date": "2025-09-22",
        "status": "现行",
    },
    {
        "doc_id": "2018车船税优惠",
        "filename": "2018年-车船税优惠政策通知.md",
        "kind": "document",
        "url": "https://www.chinatax.gov.cn/chinatax/n810341/n810765/n3359382/201807/c3730832/content.html",
        "publisher": "财政部、税务总局、工业和信息化部、交通运输部",
        "doc_number": "财税〔2018〕74号",
        "publish_date": "2018-07-10",
        "status": "现行",
    },
    {
        "doc_id": "2025智能网联准入OTA",
        "filename": "2025年-智能网联汽车准入召回与OTA管理通知.md",
        "kind": "document",
        "url": "https://www.gov.cn/zhengce/zhengceku/202503/content_7009422.htm",
        "publisher": "工业和信息化部、市场监管总局",
        "doc_number": "工信部联通装〔2025〕45号",
        "publish_date": "2025-02-28",
        "status": "现行",
    },
    {
        "doc_id": "2019缺陷汽车召回条例",
        "filename": "2019年-缺陷汽车产品召回管理条例.md",
        "kind": "document",
        "url": "https://www.gov.cn/gongbao/content/2019/content_5468948.htm",
        "publisher": "国务院",
        "doc_number": "国务院令第626号",
        "publish_date": "2019-03-02",
        "status": "现行",
    },
    {
        "doc_id": "2021汽车数据安全管理规定",
        "filename": "2021年-汽车数据安全管理若干规定.md",
        "kind": "document",
        "url": "https://www.gov.cn/gongbao/content/2021/content_5647363.htm",
        "publisher": "国家网信办等五部门",
        "doc_number": "五部门令第7号",
        "publish_date": "2021-08-16",
        "status": "现行",
    },
    {
        "doc_id": "2026工信部目录公告",
        "filename": "2026年-工信部第409批及两项车型目录公告.md",
        "kind": "source_only",
        "url": "https://www.miit.gov.cn/zwgk/zcwj/wjfb/gg/art/2026/art_00d965bfa9ea4bc89bc7613cf911c896.html",
        "publisher": "工业和信息化部",
        "doc_number": "工业和信息化部公告2026年第21号",
        "publish_date": "2026-08-12",
        "status": "现行",
        "note": "正文仅一句话，实质内容在三个附件；本文件只登记来源与附件地址，不参与检索",
    },
]

CONTENT_HINTS = (
    "pages_content",
    "TRS_Editor",
    "art-con",
    "article",
    "content",
    "gsj_htmlcon_bot",
    "xxgk_content",
)
NOISE_URL_PARTS = ("app.www.gov.cn", "/govdata/", "javascript:")
NOISE_LINE = re.compile(
    r"^(?:【[^】]{1,8}】)+$"
    r"|^打印本页$|^关闭窗口$|^返回顶部$"
    r"|^扫一扫在手机打开当前页$|^【字体：[^】]*】$"
    r"|^索\s*引\s*号[:：]|^主题分类[:：]|^公文种类[:：]"
    r"|^发文字号[:：]|^标\s*题[:：]|^发文机关[:：]"
    r"|^来\s*源[:：]|^成文日期[:：]|^字号[:：]"
)


class Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.skip_depth = 0
        self.content_depth = 0
        self.parts: list[str] = []
        self.title = ""
        self.h1 = ""
        self._in_title = False
        self._heading: str | None = None
        self._seen_h1 = False
        self.attachments: list[dict[str, str]] = []
        self._anchor: dict[str, str] | None = None

    # -- helpers ---------------------------------------------------------
    def _emit(self, text: str) -> None:
        if self.content_depth and not self.skip_depth:
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                self.parts.append(text)

    # -- HTMLParser hooks ------------------------------------------------
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.stack.append(tag)

        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = (attrs.get("href") or "").strip()
            if href:
                self._anchor = {"href": href, "text": ""}
        if tag in HEADING_TAGS and self.content_depth:
            self._heading = HEADING_TAGS[tag]
            self.parts.append("\n\n" + self._heading + " ")

        if not self.content_depth and tag == "div":
            cls = (attrs.get("class") or "") + " " + (attrs.get("id") or "")
            hint = cls.lower() + " " + (attrs.get("ergodic") or "").lower()
            if any(h.lower() in hint for h in CONTENT_HINTS):
                self.content_depth = len(self.stack)
                self.parts = []

        if tag in BLOCK_TAGS and self.content_depth:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
        if tag == "title":
            self._in_title = False
        if tag in HEADING_TAGS:
            self._heading = None
        if tag == "a" and self._anchor is not None:
            href, text = self._anchor["href"], re.sub(r"\s+", " ", self._anchor["text"]).strip()
            low = href.lower().split("?")[0]
            noise = any(part in href for part in NOISE_URL_PARTS)
            if not noise and (low.endswith(ATTACH_EXT) or "download" in low):
                self.attachments.append({"href": href, "text": text})
            self._anchor = None

        if self.content_depth and len(self.stack) == self.content_depth and tag == "div":
            self.content_depth = 0
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self._anchor is not None:
            self._anchor["text"] += data
        self._emit(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t\u3000]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        lines, prev, seen = [], None, set()
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            if line == prev or line in seen or NOISE_LINE.search(line):
                continue
            lines.append(line)
            seen.add(line)
            prev = line
        return "\n\n".join(lines).strip()


def fetch(doc: dict) -> tuple[str, str, list[dict[str, str]]]:
    resp = requests.get(
        doc["url"],
        timeout=30,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    resp.raise_for_status()
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"

    parser = Extractor()
    parser.feed(resp.text)
    body = parser.text()
    title = (parser.h1 or parser.title).strip()
    title = re.split(r"_+(?:国务院|中国政府网|中华人民共和国)", title)[0].strip()
    links = [
        {"text": a["text"], "url": urljoin(doc["url"], a["href"])}
        for a in parser.attachments
    ]
    # 去重
    seen, uniq = set(), []
    for item in links:
        if item["url"] not in seen:
            seen.add(item["url"])
            uniq.append(item)
    return title, body, uniq


def main() -> int:
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    attachments: dict[str, list[dict[str, str]]] = {}
    failures = 0

    for doc in DOCS:
        try:
            title, body, links = fetch(doc)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {doc['filename']}: {exc}")
            failures += 1
            continue

        kind = doc.get("kind", "document")
        if kind == "source_only":
            body = body + "\n\n## 附件\n\n" + "\n".join(
                f"- [{a['text'] or '附件'}]({a['url']})" for a in links
            )
        elif len(body) < 200:
            print(f"[WARN] {doc['filename']}: 正文仅 {len(body)} 字，可能抓取不全")

        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
        front = [
            "---",
            f"doc_id: {doc['doc_id']}",
            f"title: {title or '(未取到标题)'}",
            f"publisher: {doc['publisher']}",
            f"doc_number: {doc.get('doc_number', '')}",
            f"source: {doc['url']}",
            f"publish_date: {doc['publish_date']}",
            f"retrieved_date: {today}",
            "source_tier: T1",
            "license: 政府信息公开（研究使用）",
            f"category: {'source' if kind == 'source_only' else 'policy'}",
            f"status: {doc['status']}",
            f"content_sha256: {digest}",
        ]
        if doc.get("note"):
            front.append(f"note: {doc['note']}")
        front += ["---", ""]

        out_dir = ROOT / "corpus" / "政策"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / doc["filename"]).write_text(
            "\n".join(front) + body + "\n", encoding="utf-8"
        )
        attachments[doc["doc_id"]] = links
        print(f"[OK] {doc['filename']}  {len(body):>6} 字  附件 {len(links)} 个")

    manifest = ROOT / "corpus" / "政策" / "附件清单.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(attachments, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n完成：失败 {failures} 份，附件清单见 {manifest}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
