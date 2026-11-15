"""Core:身份对齐、维度表、事实表与口径标记。

这一层把 staging 的原始行变成"有业务含义的行"：两套 ID 对齐到同一个帖子、
观点打上口径标记、产品树补出品牌/车系。口径标记必须写在这里而不是查询时临时算，
否则每一级样本的规模就无法被独立核对。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterator

from ..spec.types import SemanticModel
from .paths import frozen_inputs_dir, source_path

SCHEMA = """
CREATE TABLE dim_post(
  post_id TEXT PRIMARY KEY, post_uid TEXT UNIQUE NOT NULL,
  title TEXT, url TEXT, published_at TEXT, month TEXT,
  author_id TEXT, author_nickname TEXT,
  ownership_status TEXT, quality_state TEXT,
  is_excluded INTEGER, is_duplicate INTEGER, is_spam INTEGER);

CREATE TABLE dim_user(
  user_id TEXT PRIMARY KEY, nickname TEXT, post_count INTEGER);

CREATE TABLE dim_product(
  node_id TEXT PRIMARY KEY, parent_id TEXT, label TEXT, level TEXT,
  brand TEXT, series TEXT, spec_name TEXT, is_analysis_object INTEGER);

CREATE TABLE fct_mention(
  post_id TEXT NOT NULL, post_uid TEXT NOT NULL, product_id TEXT NOT NULL,
  local_product_id TEXT, raw_name TEXT, resolution_level TEXT, status TEXT,
  review_required INTEGER,
  PRIMARY KEY(post_id, product_id));

CREATE TABLE fct_claim(
  claim_id TEXT PRIMARY KEY, post_id TEXT NOT NULL, post_uid TEXT NOT NULL,
  claim_seq INTEGER NOT NULL, month TEXT,
  aspect TEXT, sentiment TEXT, claim_type TEXT, statement TEXT,
  experience TEXT, journey TEXT, ownership TEXT, content TEXT, quote TEXT,
  evidence_json TEXT, confidence REAL, comparison_json TEXT,
  has_su7_target INTEGER, su7_is_main_target INTEGER, competing_main INTEGER,
  is_comparison INTEGER, evidence_ok INTEGER);

-- 车型归属：一条观点 × 一个被提及车型。多归属口径（提到 3 个车型各计一次）由它承载；
-- 观点属性在这里复制一份，只为了让口径与指标谓词能在同一张表上求值。
CREATE TABLE fct_claim_product(
  claim_id TEXT NOT NULL, post_id TEXT NOT NULL, product_id TEXT NOT NULL,
  role TEXT, month TEXT, aspect TEXT, sentiment TEXT, claim_type TEXT,
  experience TEXT, journey TEXT, ownership TEXT,
  has_su7_target INTEGER, su7_is_main_target INTEGER, competing_main INTEGER,
  is_comparison INTEGER, evidence_ok INTEGER,
  PRIMARY KEY(claim_id, product_id));

-- 口径成员：一行表示"这条观点属于哪一级样本"。谓词由模型给出，构建期落表，
-- 因此每一级的规模都能在库里独立复核，而不必重算整条阶梯。
CREATE TABLE claim_population(
  claim_id TEXT NOT NULL, population TEXT NOT NULL,
  PRIMARY KEY(claim_id, population));

CREATE INDEX idx_claim_aspect ON fct_claim(aspect);
CREATE INDEX idx_claim_sentiment ON fct_claim(sentiment);
CREATE INDEX idx_claim_month ON fct_claim(month);
CREATE INDEX idx_claim_population ON claim_population(population);
CREATE INDEX idx_claim_product_product ON fct_claim_product(product_id);
CREATE INDEX idx_mention_post ON fct_mention(post_id);
"""

POST_UID_RE = re.compile(r"thread/([0-9a-f]{16})/")
CLAIM_TABLE = "fct_claim"
SU7_BRAND, SU7_SERIES = "小米", "SU7"


def create(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def build(con: sqlite3.Connection, model: SemanticModel, snapshot_hash: str) -> dict[str, Any]:
    """Populate every core table from staging plus the source database."""
    source_db = source_path(model, "source_db")
    posts, users, annotations = _read_source(source_db)

    dim_posts = _build_dim_post(con, posts, annotations)
    user_count = _build_dim_user(con, users, posts)
    product_count = _build_dim_product(con)
    mention_count, unresolved_mentions = _build_fct_mention(con)
    claim_count, product_count_rows, ladder, unresolved_claims = _build_fct_claim(
        con, model, snapshot_hash)
    con.commit()
    return {
        "dim_post": dim_posts,
        "dim_user": user_count,
        "dim_product": product_count,
        "fct_mention": mention_count,
        "fct_claim": claim_count,
        "fct_claim_product": product_count_rows,
        "unresolved_mentions": unresolved_mentions,
        "unresolved_claims": unresolved_claims,
        "ladder": ladder,
    }


def _read_source(path: Path) -> tuple[list[tuple], list[tuple], dict[str, tuple]]:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        posts = list(con.execute(
            "SELECT post_id, source_url, title, published_at, author_id, "
            "author_nickname, quality_state FROM posts"))
        users = list(con.execute("SELECT user_id, nickname FROM users"))
        annotations = {row[0]: row[1:] for row in con.execute(
            "SELECT post_id, excluded, is_duplicate, spam_suspect FROM cleaning_annotations")}
    finally:
        con.close()
    return posts, users, annotations


def _build_dim_post(con: sqlite3.Connection, posts: list[tuple],
                    annotations: dict[str, tuple]) -> int:
    context = {uid: ownership for uid, ownership in con.execute(
        "SELECT post_uid, ownership_status FROM stg_post")}
    rows = []
    for post_id, url, title, published_at, author_id, nickname, quality in posts:
        match = POST_UID_RE.search(url or "")
        uid = match.group(1) if match else None
        excluded, duplicate, spam = annotations.get(post_id, (0, 0, 0))
        rows.append((
            post_id, uid, title, url, published_at,
            (published_at or "")[:7] or None,
            author_id, nickname, context.get(uid), quality,
            # excluded 存的是原因码（空串表示未排除），不是 0/1。
            int(bool(excluded)), int(duplicate or 0), int(spam or 0)))
    # 没有 thread 串的帖子无法与抽取产物对齐，留空 uid 而不是伪造一个。
    con.executemany("INSERT INTO dim_post VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def _build_dim_user(con: sqlite3.Connection, users: list[tuple],
                    posts: list[tuple]) -> int:
    counts: dict[str, int] = {}
    for _, _, _, _, author_id, _, _ in posts:
        if author_id:
            counts[author_id] = counts.get(author_id, 0) + 1
    rows = [(user_id, nickname, counts.get(user_id, 0)) for user_id, nickname in users]
    con.executemany("INSERT INTO dim_user VALUES(?,?,?)", rows)
    return len(rows)


def _build_dim_product(con: sqlite3.Connection) -> int:
    nodes = {row[0]: row for row in con.execute(
        "SELECT node_id, parent_id, label, level FROM stg_taxonomy")}

    def ancestor(node_id: str, wanted: str) -> str | None:
        seen = 0
        cursor = nodes.get(node_id)
        while cursor and seen < 10:
            if cursor[3] == wanted:
                return cursor[2]
            cursor = nodes.get(cursor[1])
            seen += 1
        return None

    rows = []
    for node_id, parent_id, label, level in nodes.values():
        if level == "brand":
            brand, series, spec = label, None, None
        elif level == "series":
            brand, series, spec = ancestor(node_id, "brand"), label, None
        elif level == "spec":
            brand = ancestor(node_id, "brand")
            series = ancestor(node_id, "series")
            spec = label
        else:
            brand = series = spec = None
        is_object = int(level == "series" and label == SU7_SERIES and brand == SU7_BRAND)
        rows.append((node_id, parent_id, label, level, brand, series, spec, is_object))
    con.executemany("INSERT INTO dim_product VALUES(?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def _build_fct_mention(con: sqlite3.Connection) -> tuple[int, int]:
    post_ids = {uid: post_id for post_id, uid in
                con.execute("SELECT post_id, post_uid FROM dim_post WHERE post_uid IS NOT NULL")}
    rows, unresolved = [], 0
    for uid, pid, raw_name, product_id, resolution, status, review in con.execute(
            "SELECT post_uid, local_product_id, raw_name, node_id, resolution_level, "
            "status, review_required FROM stg_mention"):
        post_id = post_ids.get(uid)
        if post_id is None or not product_id:
            unresolved += 1
            continue
        rows.append((post_id, uid, product_id, pid, raw_name, resolution, status,
                     int(review or 0)))
    con.executemany("INSERT OR REPLACE INTO fct_mention VALUES(?,?,?,?,?,?,?,?)", rows)
    return len(rows), unresolved


def _build_fct_claim(con: sqlite3.Connection, model: SemanticModel,
                     snapshot_hash: str) -> tuple[int, int, dict, int]:
    post_ids = {uid: (post_id, month) for post_id, uid, month in
                con.execute("SELECT post_id, post_uid, month FROM dim_post "
                            "WHERE post_uid IS NOT NULL")}
    ownership = {uid: value for uid, value in
                 con.execute("SELECT post_uid, ownership_status FROM stg_post")}
    mentions = {(uid, pid): (node_id, brand, series, status)
                for uid, pid, node_id, brand, series, status
                in con.execute("SELECT post_uid, local_product_id, node_id, brand, series, "
                               "status FROM stg_mention")}

    rows: list[tuple] = []
    product_rows: list[tuple] = []
    unresolved = 0
    blocks: dict[str, dict] = {}
    current_uid = None

    for record in _claim_rows(con):
        (uid, seq, aspect, sentiment, claim_type, statement, experience, journey,
         content, quote, evidence_json, confidence, comparison_json, targets_json) = record
        target = post_ids.get(uid)
        if target is None:
            unresolved += 1
            continue
        post_id, month = target
        if uid != current_uid:
            current_uid = uid
            blocks = _load_blocks(uid)

        resolved = []
        for item in json.loads(targets_json or "[]"):
            mapped = mentions.get((uid, item.get("product_id")))
            if mapped:
                resolved.append((mapped, item.get("role")))
        has_su7 = any(_is_su7(m) for m, _role in resolved)
        su7_main = any(_is_su7(m) and role == "主要讨论对象" for m, role in resolved)
        competing = any(role == "主要讨论对象" and not _is_su7(m) for m, role in resolved)
        is_comparison = 1 if comparison_json else 0
        evidence_ok = _evidence_ok(json.loads(evidence_json or "[]"), blocks)

        claim_id = hashlib.sha256(f"{snapshot_hash}:{uid}:{seq}".encode()).hexdigest()[:20]
        rows.append((
            claim_id, post_id, uid, seq, month, aspect, sentiment, claim_type, statement,
            experience, journey, ownership.get(uid), content, quote, evidence_json,
            confidence, comparison_json,
            int(has_su7), int(su7_main), int(competing), is_comparison, evidence_ok))

        # 多归属：一条观点提到 N 个已映射车型就落 N 行，重复提及同一车型只算一次。
        seen_products: set[str] = set()
        for (node_id, _brand, _series, status), role in resolved:
            if status != "mapped" or not node_id or node_id in seen_products:
                continue
            seen_products.add(node_id)
            product_rows.append((
                claim_id, post_id, node_id, role, month, aspect, sentiment, claim_type,
                experience, journey, ownership.get(uid),
                int(has_su7), int(su7_main), int(competing), is_comparison, evidence_ok))

    con.executemany("INSERT INTO fct_claim VALUES(" + ",".join("?" * 22) + ")", rows)
    con.executemany("INSERT INTO fct_claim_product VALUES(" + ",".join("?" * 16) + ")",
                    product_rows)
    # 行上的标记只回答"这条观点看到了什么"；"属于哪一级样本"由模型谓词在落表后判定，
    # 这样口径阶梯只有一份定义，也能在库里逐级复核。
    ladder = _mark_populations(con, model)
    return len(rows), len(product_rows), ladder, unresolved


def _mark_populations(con: sqlite3.Connection, model: SemanticModel) -> dict[str, int | None]:
    """把每条观点所属的口径级写进 claim_population，并回报各级规模。

    谓词来自模型（加载期已过白名单校验），这里只做组合与执行。冻结成员由导入
    决定、无法由谓词重算，记为 None 而不是编一个 0。
    """
    claim_dataset = next((name for name, dataset in model.datasets.items()
                          if dataset.source == CLAIM_TABLE), None)
    ladder: dict[str, int | None] = {}
    members: list[tuple[str, str]] = []
    for name, population in model.populations.items():
        if population.dataset != claim_dataset:
            continue
        if population.source != "rule":
            ladder[name] = None
            continue
        predicate = _predicate(model, population)
        claim_ids = con.execute(
            f"SELECT claim_id FROM fct_claim WHERE {predicate}").fetchall()
        members.extend((claim_id, name) for (claim_id,) in claim_ids)
        ladder[name] = len(claim_ids)
    con.executemany("INSERT OR REPLACE INTO claim_population VALUES(?,?)", members)
    return ladder


def _predicate(model: SemanticModel, population) -> str:
    """由本级的谓词与其祖先谓词合成一条 SQL 条件，使包含关系显式成立。"""
    clauses: list[str] = []
    cursor = population
    while cursor is not None:
        if cursor.filter:
            clauses.append(f"({cursor.filter})")
        cursor = model.populations.get(cursor.parent) if cursor.parent else None
    return " AND ".join(clauses) or "1 = 1"


def _claim_rows(con: sqlite3.Connection) -> Iterator[tuple]:
    cursor = con.execute(
        "SELECT post_uid, claim_seq, aspect, sentiment, claim_type, statement, experience, "
        "journey, content, quote, evidence_json, confidence, comparison_json, "
        "target_products_json FROM stg_claim ORDER BY post_uid, claim_seq")
    yield from cursor


def _load_blocks(post_uid: str) -> dict[str, dict]:
    """原始 block 文本；缺失时不臆测，交由 evidence_ok 记为未知。"""
    path = frozen_inputs_dir() / f"{post_uid}.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {block.get("block_id"): block for block in payload.get("blocks") or []}


def _norm(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).casefold()


def _evidence_ok(evidence: list[dict], blocks: dict[str, dict]) -> int | None:
    """1 通过、0 不通过、None 无原始文本无法判断。

    三态是必须的：把"无法判断"记成 0，会让口径阶梯静默缩小；
    记成 1，则会放进未经验证的观点。
    """
    if not evidence:
        return 0
    if not blocks:
        return None
    checks = []
    for item in evidence:
        block = blocks.get(item.get("block_id"), {})
        expected = "text" if item.get("source_type") == "text" else "image"
        text = block.get("text", "") if expected == "text" else block.get("summary", "")
        checks.append(bool(item.get("quote")) and block.get("type") == expected
                      and _norm(item.get("quote")) in _norm(text))
    return 1 if all(checks) else 0


def _is_su7(target: tuple) -> bool:
    _node_id, brand, series, status = target
    return brand == SU7_BRAND and series == SU7_SERIES and status == "mapped"
