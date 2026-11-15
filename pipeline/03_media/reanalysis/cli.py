# -*- coding: utf-8 -*-
"""Command-line driver for the AUTO-007 context-enhanced re-analysis.

Subcommands
  verify   -- enforce the 798-image data contract (joins, unique anchors, posts)
  connect  -- confirm credentials parse and the endpoint is reachable
  manifest -- write the 798-entry before-manifest + distribution to OUT_DIR
  pilot    -- run a small stratified pilot (6-10 imgs) into an isolated subdir
  run      -- run all 798 into OUT_DIR (checkpointed, resumable)
  report   -- consolidate, compare before/after, stratified eval, write HTML

Credentials are reused locally, never printed or persisted. Bulky outputs go to
OUT_DIR (non-committed). The 100 human labels are used only offline (selection
+ stratification); they are never placed in a model payload.
"""
import argparse
import collections
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config
from . import compare as cmp
from . import loader
from . import runner
from .validate import ExtractError, safe_usage


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


class LogWriter(object):
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "a", encoding="utf-8")
        else:
            self._fh = None

    def __call__(self, msg):
        line = "[%s] %s" % (_utcnow_iso(), msg)
        print(line, flush=True)
        if self._fh:
            self._fh.write(line + "\n")
            self._fh.flush()

    def close(self):
        if self._fh:
            self._fh.close()


def _mask(url):
    return url


def build_ctx(concurrency=config.DEFAULT_CONCURRENCY, max_retries=config.MAX_RETRIES):
    """Assemble the immutable run context (versions, fingerprints, inputs)."""
    model, base, key = runner.load_connection()
    template = config.PROMPT_FILE.read_text(encoding="utf-8")
    schema = json.loads(config.SCHEMA_FILE.read_text(encoding="utf-8"))
    prompt_version = runner.version_from_file(config.PROMPT_FILE)
    schema_version = runner.version_from_file(config.SCHEMA_FILE)
    params_fp = runner.make_params_fingerprint(config.PARAMS)
    return {
        "model": model,
        "base": base,
        "key": key,
        "params": dict(config.PARAMS),
        "params_fingerprint": params_fp,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "context_version": config.CONTEXT_VERSION,
        "max_retries": max_retries,
        "concurrency": concurrency,
        "template": template,
        "schema": schema,
    }


def _post_body_chars(entry):
    total = 0
    for e in entry["mm"]:
        if isinstance(e, dict) and e.get("type") == "text":
            total += len(e.get("v") or "")
    return total


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #
def cmd_verify(args):
    before = loader.load_baseline_before()
    m003 = loader.load_csv003()
    posts = loader.load_posts()
    idx = loader.build_before_index(before, m003, posts)
    body_lens = [_post_body_chars(e) for e in idx.values()]
    long1500 = sum(1 for n in body_lens if n >= 1500)
    long3000 = sum(1 for n in body_lens if n >= 3000)
    distinct_posts = len({e["post_id"] for e in idx.values()})
    report = {
        "checked_at": _utcnow_iso(),
        "baseline_irrelevant_success": len(before),
        "joined_index_size": len(idx),
        "distinct_posts": distinct_posts,
        "per_image_body_median_chars": int(statistics.median(body_lens)) if body_lens else None,
        "images_in_posts_ge_1500_chars": long1500,
        "images_in_posts_ge_3000_chars": long3000,
        "csv003_rows": len(m003),
        "posts_loaded": len(posts),
        "model": None,
    }
    try:
        model, base, _key = runner.load_connection()
        report["model"] = model
        report["endpoint_host"] = base.split("/")[2] if "//" in base else base
    except ExtractError as err:
        report["connection_error"] = err.code
    out = Path(args.out_dir) / "verify.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if len(idx) != 798:
        print("[verify] WARNING: joined index is %d, expected 798" % len(idx), file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- #
# connect
# --------------------------------------------------------------------------- #
def cmd_connect(args):
    model, base, key = runner.load_connection()
    print("[connect] model=%s endpoint_host=%s" % (model, base.split("/")[2] if "//" in base else base))
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "请只回复 OK 两个字母。"}],
        "max_tokens": 8,
        "temperature": 0.0,
        "stream": False,
    }
    try:
        resp, status = runner.call_api(base, key, payload, timeout=30)
        content = (resp.get("choices") or [{}])[0].get("message", {}).get("content", "")
        print("[connect] http=%s reply=%r usage=%s" % (status, content, safe_usage(resp.get("usage"))))
        print("[connect] OK: endpoint reachable, auth valid.")
        return 0
    except ExtractError as err:
        print("[connect] FAILED: %s (http=%s)" % (err.code, err.http_status), file=sys.stderr)
        return 1


# --------------------------------------------------------------------------- #
# manifest
# --------------------------------------------------------------------------- #
def cmd_manifest(args):
    idx = loader.build_before_index()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mpath = out_dir / "before_manifest.jsonl"
    with open(mpath, "w", encoding="utf-8") as fh:
        for iid in sorted(idx):
            e = idx[iid]
            fh.write(json.dumps({
                "image_id": iid,
                "input_sha256": e["input_sha256"],
                "relpath": e["relpath"],
                "post_id": e["post_id"],
                "url": e["url"],
                "source_url": e["source_url"],
                "title": e["title"],
                "anchor_idx": e["anchor_idx"],
                "post_body_chars": _post_body_chars(e),
            }, ensure_ascii=False) + "\n")
    print("[manifest] wrote %d entries -> %s" % (len(idx), mpath))
    return 0


# --------------------------------------------------------------------------- #
# pilot selection (labels used offline only; NEVER placed in the payload)
# --------------------------------------------------------------------------- #
def select_pilot(index, qc_labels, size=10, seed=20261010):
    """Stratified pilot: spread across removable/retain/doubtful + long posts.

    The labels decide WHICH images to pick for coverage; the model is never told
    anything about them (they are not in any payload).
    """
    import random
    rnd = random.Random(seed)
    by_label = collections.defaultdict(list)
    for iid, lab in qc_labels.items():
        if iid in index:
            by_label[lab].append(iid)
    for lst in by_label.values():
        rnd.shuffle(lst)

    picked = []
    seen = set()
    # balanced draw from each labeled group
    per_group = max(1, size // 3)
    for lab in ("removable", "retain", "doubtful"):
        for iid in by_label.get(lab, [])[:per_group]:
            if iid not in seen:
                picked.append(iid)
                seen.add(iid)
    # top up with long-post images (exercise budget/truncation/expansion)
    long_ids = sorted(
        (iid for iid in index if _post_body_chars(index[iid]) >= 1500),
        key=lambda i: _post_body_chars(index[i]), reverse=True,
    )
    for iid in long_ids:
        if len(picked) >= size:
            break
        if iid not in seen:
            picked.append(iid)
            seen.add(iid)
    # final top-up with arbitrary remaining
    if len(picked) < size:
        rest = [iid for iid in sorted(index) if iid not in seen]
        rnd.shuffle(rest)
        for iid in rest:
            if len(picked) >= size:
                break
            picked.append(iid)
            seen.add(iid)
    return picked[:size]


def cmd_pilot(args):
    index = loader.build_before_index()
    qc_labels = cmp.load_qc_labels()
    ids = select_pilot(index, qc_labels, size=args.size)
    print("[pilot] selected %d images (labels used offline only):" % len(ids))
    for iid in ids:
        print("   %-28s label=%-9s body_chars=%d" % (
            iid, qc_labels.get(iid, "-"), _post_body_chars(index[iid])))
    entries = [index[i] for i in ids]
    ctx = build_ctx(concurrency=args.concurrency)
    out_dir = Path(args.out_dir) / ("pilot-%s" % args.seed)
    log = LogWriter(out_dir / "run.log")
    try:
        counters = runner.run_batch(entries, ctx, out_dir, resume=not args.no_resume, log=log)
    finally:
        log.close()
    print("[pilot] done -> %s" % out_dir)
    print(json.dumps(counters, ensure_ascii=False, indent=2))
    return 0


# --------------------------------------------------------------------------- #
# run (full)
# --------------------------------------------------------------------------- #
def cmd_run(args):
    index = loader.build_before_index()
    entries = [index[i] for i in sorted(index)]
    ctx = build_ctx(concurrency=args.concurrency)
    out_dir = Path(args.out_dir)
    log = LogWriter(out_dir / "run.log")
    try:
        counters = runner.run_batch(entries, ctx, out_dir, resume=not args.no_resume, log=log)
    finally:
        log.close()
    print("[run] done -> %s" % out_dir)
    print(json.dumps(counters, ensure_ascii=False, indent=2))
    return 0


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def cmd_report(args):
    index = loader.build_before_index()
    out_dir = Path(args.out_dir)
    by_id = runner.consolidate(out_dir / "results.jsonl")
    runner.write_final(by_id, out_dir)
    summary = runner.summarize(by_id)

    after_by_id = by_id
    rows = cmp.build_comparison(index, after_by_id)
    jpath, cpath = cmp.write_comparison_outputs(rows, out_dir)

    qc_labels = cmp.load_qc_labels()
    strat = cmp.stratified_eval(rows, qc_labels)
    spath = out_dir / "stratified_eval.json"
    spath.write_text(json.dumps(strat, ensure_ascii=False, indent=2), encoding="utf-8")

    meta = (
        "生成于 %s · 共 %d 张 · 模型 %s · context_version=%s · 标签(81移除/11保留/8存疑)仅作离线分层，未送入模型"
        % (_utcnow_iso(), len(rows), summary.get("model", "?"), config.CONTEXT_VERSION)
    )
    hpath = cmp.render_html(rows, qc_labels, index, meta, out_dir / cmp.HTML_FILENAME)

    report = {
        "generated_at": _utcnow_iso(),
        "change_id": config.CHANGE_ID,
        "model": _model_of(summary, by_id),
        "summary": summary,
        "outputs": {
            "results_final": str(out_dir / "results_final.jsonl"),
            "comparison_jsonl": str(jpath),
            "comparison_csv": str(cpath),
            "stratified_eval": str(spath),
            "html": str(hpath),
        },
        "notes": [
            "变化不代表改进；增强后的质量仍需新的独立人工判断。",
            "technical_failure 与 证据不足 为不同状态，前者会由 resume 重试。",
            "100 个人工标签仅用于离线分层，从未进入模型输入。",
        ],
    }
    rpath = out_dir / "report.json"
    rpath.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _model_of(summary, by_id):
    for r in by_id.values():
        if r.get("model"):
            return r["model"]
    return summary.get("model")


# --------------------------------------------------------------------------- #
def main(argv=None):
    p = argparse.ArgumentParser(prog="a007")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_out(sp, default=str(config.OUT_DIR)):
        sp.add_argument("--out-dir", default=default)

    sp = sub.add_parser("verify", help="enforce the 798-image data contract")
    add_out(sp)
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser("connect", help="check credentials + endpoint reachability")
    sp.set_defaults(func=cmd_connect)

    sp = sub.add_parser("manifest", help="write the before-manifest")
    add_out(sp)
    sp.set_defaults(func=cmd_manifest)

    sp = sub.add_parser("pilot", help="small stratified pilot into an isolated subdir")
    add_out(sp)
    sp.add_argument("--size", type=int, default=10)
    sp.add_argument("--concurrency", type=int, default=config.DEFAULT_CONCURRENCY)
    sp.add_argument("--seed", type=int, default=20261010)
    sp.add_argument("--no-resume", action="store_true")
    sp.set_defaults(func=cmd_pilot)

    sp = sub.add_parser("run", help="run all 798 (checkpointed)")
    add_out(sp)
    sp.add_argument("--concurrency", type=int, default=config.DEFAULT_CONCURRENCY)
    sp.add_argument("--no-resume", action="store_true")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("report", help="consolidate + compare + stratified eval + HTML")
    add_out(sp)
    sp.set_defaults(func=cmd_report)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
