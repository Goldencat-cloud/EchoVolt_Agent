"""Conservative HTML adapters. Unknown structures fail, never use whole-page fallbacks."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin

from ..contracts import IngestionError, Record
from ..quality import evaluate
from .basic import clean_text, number, parse_time, user_id


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    locator: str = ""

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def text(self):
        if self.tag in {"script", "style"}:
            return ""
        return "".join(c.text() if isinstance(c, Node) else c for c in self.children)

    def has_class(self, name):
        return name in self.attrs.get("class", "").split()


class Tree(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        n = Node(tag, dict(attrs), locator="html:%s:%s" % self.getpos())
        self.stack[-1].children.append(n)
        if tag not in {"img", "input", "br", "hr", "meta", "link", "source", "area", "wbr", "embed"}:
            self.stack.append(n)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, text):
        self.stack[-1].children.append(text)


def check_page(text):
    if any(x in text[:100000] for x in ["用户访问安全认证", "访问过于频繁", "请完成安全验证"]):
        raise IngestionError("blocked")


def forum_list(text):
    check_page(text)
    root = Tree(text).root
    result = []
    for node in root.walk():
        tid = node.attrs.get("data-topicid", "")
        if not tid.isdigit():
            continue
        links = [n for n in node.walk() if n.tag == "a" and "/bbs/thread/" in n.attrs.get("href", "")]
        if not links:
            raise IngestionError("list_topic_link_missing")
        times = [n for n in node.walk() if "information__item" in n.attrs.get("class", "") and re.search(r"\d{4}/\d{1,2}/\d{1,2}", n.text())]
        t = re.search(r"\d{4}/\d{1,2}/\d{1,2}(?:\s+\d{2}:\d{2}:\d{2})?", times[0].text()) if times else None
        homes = list(dict.fromkeys(urljoin("https://i.autohome.com.cn", n.attrs.get("href", "")) for n in node.walk() if n.tag == "a" and user_id(n.attrs.get("href", ""))))
        marks=[n.text().strip() for n in node.walk() if n.tag=='i' and any(c.startswith('mark') for c in n.attrs.get('class','').split())]
        pinned=any(node.attrs.get(k,'').lower() in {'1','true'} for k in ['data-istop','data-is-top','data-top','istop']) or any('置顶' in m for m in marks) or bool({'top','pinned','sticky'}.intersection(node.attrs.get('class','').split()))
        authors=[n.text().strip() for n in node.walk() if n.tag=='a' and user_id(n.attrs.get('href',''))]
        result.append({"post_id": tid, "url": urljoin("https://club.autohome.com.cn", links[0].attrs["href"]).split("#")[0],
                       "published_raw": t[0] if t else "", "author_home": homes[0] if len(homes) == 1 else "",
                       "user_id": user_id(homes[0]) if len(homes) == 1 else "",'is_pinned':pinned,
                       'author_nickname':authors[0] if len(set(authors))==1 else None,'tags':marks,
                       'list_image_count':sum(1 for n in node.walk() if n.tag=='img' and any(x in n.attrs.get('src','') for x in ['autoimg','album']))})
    # An unrecognised response is not proof that the forum is empty.
    if not result:
        raise IngestionError("list_empty_or_unrecognized")
    return result


def post_page(text, source_id, source_url, retrieved_at, author_hint=None):
    check_page(text)
    root = Tree(text).root
    candidates = [n for n in root.walk() if n.has_class("post-container")]
    if len(candidates) != 1:
        raise IngestionError("owner_body_ambiguous_or_missing")
    body = candidates[0]
    sequence = []
    excluded = {"quote", "signature", "reply", "replies", "avatar", "reference"}

    def visit(n):
        if n.tag in {"script", "style", "blockquote"} or excluded.intersection(n.attrs.get("class", "").split()):
            return
        if n.tag == "img":
            url = next((n.attrs[k] for k in ["data-src", "data-original", "src"] if n.attrs.get(k) and not n.attrs[k].startswith("data:")), None)
            if url:
                sequence.append({"kind": "image", "value": urljoin(source_url, url), "locator": n.locator})
            return
        vid = n.attrs.get("data-vid") or n.attrs.get("videoid")
        if vid:
            sequence.append({"kind": "video", "value": vid, "locator": n.locator})
            return
        for child in n.children:
            if isinstance(child, Node):
                visit(child)
            elif child.strip():
                sequence.append({"kind": "text", "value": child, "locator": n.locator})

    visit(body)
    if not sequence:
        raise IngestionError("owner_body_empty_unverified")
    times = [n.attrs.get("datetime") or n.text().strip() for n in root.walk()
             if n.tag == "time" and (n.attrs.get("itemprop") == "datePublished" or n.has_class("publish-time"))]
    times += [n.attrs.get("content") for n in root.walk() if n.tag == "meta" and n.attrs.get("property") == "article:published_time"]
    for n in root.walk():
        if n.has_class("post-handle-publish"):
            match = re.search(r"20\d{2}-\d{1,2}-\d{1,2}\s+\d{2}:\d{2}:\d{2}", n.text())
            if match:
                times.append(match[0])
    times = list(dict.fromkeys(t for t in times if t))
    titles = [n.text().strip() for n in root.walk() if n.tag == "h1"]
    if not titles:
        titles = [n.attrs.get("content", "") for n in root.walk() if n.tag == "meta" and n.attrs.get("property") == "og:title"]
    if not titles:
        titles = [n.text().strip() for n in root.walk() if n.tag == "title"]
    author = [n.attrs.get("href", "") for n in root.walk() if n.tag == "a" and n.attrs.get("rel") == "author"]
    raw_text = "\n".join(s["value"] for s in sequence if s["kind"] == "text")
    time_info = parse_time(times[0] if len(times) == 1 else "", retrieved_at)
    if time_info["value"] is None and author_hint and author_hint.get("post_id") == source_id:
        fallback = parse_time(str(author_hint.get("published_raw") or "").replace("/", "-"), retrieved_at)
        if fallback["value"] is not None:
            fallback["basis"] = "list_page_time"
            fallback["raw"] = str(author_hint.get("published_raw"))
            time_info = fallback
    record = Record("posts", source_id, {"post_id": source_id, "source_url": source_url,
                    "title": titles[0] if len(titles) == 1 else "", "text_content": raw_text,
                    "clean_text": clean_text(raw_text), "segments": sequence, "sequence_status": "ordered",
                    "time": time_info,
                    "author_home": author[0] if len(set(author)) == 1 else "", "user_id": user_id(author[0]) if len(set(author)) == 1 else "",
                    "views": None, "replies": None}, body.locator, parser_version="autohome-page-1")
    if not record.data["user_id"] and author_hint and author_hint.get("post_id") == source_id and author_hint.get("user_id") == user_id(author_hint.get("author_home")):
        record.data["user_id"] = author_hint["user_id"]
        record.data["author_home"] = author_hint["author_home"]
        record.data["author_source"] = {"response_id": author_hint.get("response_id"), "locator": "list-item:" + source_id}
    if not record.data["title"]:
        record.issues.append("title_missing_or_ambiguous")
    if not record.data["user_id"]:
        record.issues.append("author_missing_or_ambiguous")
    if author_hint:
        record.data.update(list_time_raw=author_hint.get('published_raw'),list_image_count=author_hint.get('list_image_count'),
                           tags=author_hint.get('tags'),list_author_nickname=author_hint.get('author_nickname'),
                           list_author_home_url=author_hint.get('author_home'),author_nick=author_hint.get('author_nickname'))
    return evaluate(record)


def user_page(text, source_id, retrieved_at):
    check_page(text)
    root = Tree(text).root
    plain = clean_text(root.text())
    canonical = [n.attrs.get("href", "") for n in root.walk() if n.tag == "link" and n.attrs.get("rel") == "canonical"]
    if canonical and {user_id(u) for u in canonical}!={source_id}:
        raise IngestionError('user_identity_conflict')
    if not (any(user_id(u) == source_id for u in canonical) or re.search(r"用户ID\s*[:：]\s*" + re.escape(source_id) + r"\b", plain)):
        raise IngestionError("user_identity_unverified")
    raw = [n.attrs.get("value", "") for n in root.walk() if n.tag == "input" and (n.attrs.get("id") == "hdsex" or n.attrs.get("name") == "hdsex")]
    raw = raw[0] if len(raw) == 1 else ""
    names = [n.text().strip() for n in root.walk() if n.tag == "h1"]
    values = {}
    for node in root.walk():
        href = node.attrs.get("href", "")
        for key in ["followers", "following"]:
            if re.search(r"/" + re.escape(source_id) + "/" + key + r"(?:$|[/?])", href):
                match = re.search(r"[\d,]+", node.text())
                values[key] = number(match[0]) if match else None
    m = re.search(r"IP属地\s*[:：]\s*([^\s]+)", plain)
    return evaluate(Record("users", source_id, {"source_url": f"https://i.autohome.com.cn/{source_id}/home.html",
                           "nickname": names[0] if len(names) == 1 else None, "sex_raw": raw,
                           "sex_explicit": {"1": "男", "2": "女"}.get(raw), "sex_inferred": None,
                           "sex_source": "hdsex" if raw else "", "followers": values.get("followers"),
                           "following": values.get("following"), "ip_location": m[1] if m else None,
                           "csv_location": None, "fetched_at": retrieved_at, "status": "ok"}, "html:user-home", parser_version="autohome-page-1"))
