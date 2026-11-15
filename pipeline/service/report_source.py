"""Read-only knowledge source for citation QA over the displayed report.

The right-hand pane serves the auto-023 designed report
(06_reporting/agent-kb/output/report.html). This module extracts that very
document (read-only; the artifact on disk is never modified) into
section-structured text so the Q&A answers cite the sections the user can
actually see, and citations can scroll the report to the right place.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_HTML = ROOT / "06_reporting" / "agent-kb" / "output" / "report.html"
CITE_RE = re.compile(r"\[([A-Za-z0-9\-]{1,24})\]")


class _ReportParser(HTMLParser):
    """Collect text per section (id + title) from the designed report."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[dict[str, Any]] = []
        self._stack: list[dict[str, Any]] = []
        self._skip = 0
        self._title_depth = 0

    # -- tags ---------------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
            return
        if self._skip:
            return
        attributes = dict(attrs)
        if tag == "section":
            self._stack.append({"id": attributes.get("id"), "title_parts": [], "parts": []})
            return
        if tag == "div" and "cover" in (attributes.get("class") or ""):
            self._stack.append({"id": "cover", "title_parts": [], "parts": []})
            return
        if tag in ("h1", "h2", "h3"):
            self._title_depth += 1
        elif tag == "tr" and self._stack:
            self._stack[-1]["parts"].append("\n- ")
        elif tag in ("td", "th") and self._stack:
            self._stack[-1]["parts"].append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            if self._skip:
                self._skip -= 1
            return
        if self._skip:
            return
        if tag in ("h1", "h2", "h3") and self._title_depth:
            self._title_depth -= 1
        elif tag in ("section", "div") and self._stack:
            section = self._stack.pop()
            if self._stack:
                self._stack[-1]["parts"].append(section["parts"] and "\n" or "\n")
            else:
                self.sections.append(section)

    def handle_data(self, data: str) -> None:
        if self._skip or not self._stack:
            return
        text = data.strip()
        if not text:
            return
        current = self._stack[-1]
        if self._title_depth:
            current["title_parts"].append(text)
        else:
            current["parts"].append(text)


def _clean(parts: list[Any]) -> str:
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, str):
            chunks.append(part)
        else:
            chunks.append(str(part))
    text = " ".join(chunks)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sections_from_markdown(md: str, prefix: str = "agent-") -> list[dict[str, Any]]:
    """Parse a Markdown report into citable sections (heading-based ids).

    Heading level 1-3 opens a new section with synthetic id ``<prefix>N`` in
    document order; content before the first heading is dropped. No fallback
    section is invented for heading-less documents (callers decide).
    """
    sections: list[dict[str, Any]] = []
    current: dict[str, str] | None = None
    for line in (md or "").splitlines():
        heading = re.match(r"^#{1,3}\s+(.+?)\s*$", line)
        if heading:
            current = {"id": f"{prefix}{len(sections) + 1}",
                       "title": heading.group(1), "text": ""}
            sections.append(current)
        elif current is not None:
            current["text"] += line + "\n"
    for section in sections:
        section["text"] = section["text"].strip()
    return sections


def load_sections() -> list[dict[str, Any]]:
    """Return [{id, title, text}] for the displayed report (empty if absent)."""
    import report_publisher
    published = report_publisher.latest_published()
    if published:
        sections = sections_from_markdown(published["markdown"])
        if not sections and published["markdown"].strip():
            sections.append({"id": "agent-report", "title": published["meta"].get("title", "深度分析报告"),
                             "text": published["markdown"]})
        return sections
    if not REPORT_HTML.is_file():
        return []
    parser = _ReportParser()
    parser.feed(REPORT_HTML.read_text(encoding="utf-8"))
    result: list[dict[str, Any]] = []
    for section in parser.sections:
        title = " ".join(section["title_parts"]).strip()
        text = _clean(section["parts"])
        if not title and not text:
            continue
        result.append({"id": section["id"] or "", "title": title, "text": text})
    return result


def build_context(sections: list[dict[str, Any]] | None = None) -> str:
    """Render the report as a citable context block: 【id title】 + text."""
    sections = sections if sections is not None else load_sections()
    blocks = []
    for section in sections:
        label = section["id"]
        title = section["title"]
        header = f"【{label}】" + (f" {title}" if title else "")
        blocks.append(f"{header}\n{section['text']}")
    return "\n\n".join(blocks)


def known_ids(sections: list[dict[str, Any]] | None = None) -> set[str]:
    sections = sections if sections is not None else load_sections()
    return {s["id"] for s in sections if s["id"]}


def section_labels(sections: list[dict[str, Any]] | None = None) -> dict[str, str]:
    sections = sections if sections is not None else load_sections()
    return {s["id"]: s["title"] for s in sections if s["id"]}


def parse_citations(answer: str, sections: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Extract cited section ids from an answer and validate them."""
    sections = sections if sections is not None else load_sections()
    valid = known_ids(sections)
    labels = section_labels(sections)
    cited: list[str] = []
    for match in CITE_RE.finditer(answer or ""):
        anchor = match.group(1)
        if anchor not in cited:
            cited.append(anchor)
    return {"cited": cited,
            "valid": [a for a in cited if a in valid],
            "unknown": [a for a in cited if a not in valid],
            "sections": [{"id": a, "title": labels.get(a, "")} for a in cited if a in valid]}
