# -*- coding: utf-8 -*-
"""AUTO-008 command-line entry points.

  build   -- Phase 1 (offline): integrations + all input-side audit products.
  smoke   -- representative online smoke (no-image/short/long/AUTO-007/missing/
             citation-suspicious); calibrates output budget.
  run     -- Phase 2 (online): full 9,701 run, checkpointed, resumable.
  report  -- Phase 3 (offline): finals, comparison, cost rollup, 10 checks.
  verify  -- run only the ten verification checks.

Run as ``python -m a008.cli <cmd>`` from the experiment directory.
"""
import argparse
import json
from collections import Counter
from pathlib import Path

from . import audit
from . import compare
from . import config
from . import integrate
from . import join
from . import loader
from . import prompt as promptmod
from . import runner
from . import select
from . import tokens
from . import util
from . import verify


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def load_inputs():
    posts = loader.read_csv_dicts(config.CSV004)
    manifest = loader.read_csv_dicts(config.CSV003)
    res006 = loader.read_jsonl(config.RES006)
    res007 = loader.read_jsonl(config.RES007)
    return posts, manifest, res006, res007


def build_integrations(model, params, params_fp):
    posts, manifest, res006, res007 = load_inputs()
    pair_map, ambiguous = join.build_pair_map(manifest)
    t006 = select.build_006_table(res006)
    t007 = select.build_007_table(res007)
    prompt_text, prompt_sha256 = promptmod.load_prompt()
    integs = integrate.build_all_integrations(
        posts, pair_map, t006, t007, prompt_text, prompt_sha256,
        config.PROMPT_VERSION, config.SCHEMA_VERSION, config.CHUNK_POLICY_VERSION,
        model, params, params_fp)
    return integs, pair_map, ambiguous, t006, t007, res007


def make_ctx(model, base, key, params, params_fp, budget, concurrency, max_retries):
    prompt_text, prompt_sha256 = promptmod.load_prompt()
    synth_text, synth_sha256 = promptmod.load_synthesis_prompt()
    schema = json.loads(config.SCHEMA_FILE.read_text(encoding="utf-8"))
    return {
        "model": model, "base": base, "key": key,
        "params": params, "params_fingerprint": params_fp,
        "prompt_text": prompt_text, "prompt_sha256": prompt_sha256,
        "prompt_version": config.PROMPT_VERSION,
        "synth_text": synth_text, "synth_sha256": synth_sha256,
        "synth_version": config.SYNTH_VERSION,
        "schema": schema, "schema_version": config.SCHEMA_VERSION,
        "chunk_policy_version": config.CHUNK_POLICY_VERSION,
        "budget": budget, "max_retries": max_retries, "concurrency": concurrency,
    }


def _effective_params(args):
    params = dict(config.PARAMS)
    params["max_tokens"] = args.max_tokens
    return params


def _params_fp(params):
    return util.make_params_fingerprint(params)


def bucket_stats(integs):
    c = Counter()
    for i in integs:
        for s in i["image_sources"]:
            if not s["mapped"]:
                c["unmapped"] += 1
            elif s.get("source") == "AUTO-006":
                c["AUTO-006"] += 1
            elif s.get("source") == "AUTO-007":
                c["AUTO-007"] += 1
            elif s.get("source") == "AUTO-006-fallback":
                c["AUTO-006-fallback"] += 1
            else:
                c["null_summary"] += 1
    return dict(c)


class Tee:
    def __init__(self, path):
        self.fh = open(path, "a", encoding="utf-8")

    def __call__(self, *a):
        msg = " ".join(str(x) for x in a)
        print(msg)
        self.fh.write(msg + "\n")
        self.fh.flush()

    def close(self):
        try:
            self.fh.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# build (Phase 1, offline)
# --------------------------------------------------------------------------- #
def cmd_build(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    model = runner.load_model_name()
    params = _effective_params(args)
    params_fp = _params_fp(params)
    integs, pair_map, ambiguous, t006, t007, res007 = build_integrations(model, params, params_fp)

    with open(out / "integration.jsonl", "w", encoding="utf-8") as fh:
        for integ in integs:
            fh.write(json.dumps(integ, ensure_ascii=False) + "\n")

    audit.write_input_hashes(
        [("csv004", config.CSV004), ("csv003", config.CSV003),
         ("res006", config.RES006), ("res007", config.RES007)],
        out / "input_hashes.json")
    audit.write_model_inputs(integs, out / "model_inputs.jsonl")
    audit.write_image_positions_audit(integs, out / "image_positions_audit.jsonl")
    audit.write_auto007_citation_suspicious(res007, integs,
                                            out / "auto007_citation_suspicious_posts.json")
    audit.write_unused_auto007(res007, integs, out / "unused_auto007_results.json")

    prompt_text, prompt_sha256 = promptmod.load_prompt()
    max_est = max((i["est_input_tokens"] for i in integs), default=0)
    no_image = sum(1 for i in integs if not i["has_images"])
    stats = {
        "phase": "build",
        "model": model,
        "prompt_sha256": prompt_sha256,
        "prompt_version": config.PROMPT_VERSION,
        "total_posts": len(integs),
        "unique_post_id": len({i["post_id"] for i in integs}),
        "no_image_posts": no_image,
        "with_image_posts": len(integs) - no_image,
        "ambiguous_pairs": len(ambiguous),
        "selection_buckets": bucket_stats(integs),
        "max_est_input_tokens": max_est,
        "input_token_budget": args.budget,
        "would_chunk": sum(1 for i in integs if i["est_input_tokens"] > args.budget),
        "est_method": tokens.TOKEN_METHOD,
    }
    (out / "build_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print("[build] wrote integration.jsonl + audit products to", out)


# --------------------------------------------------------------------------- #
# smoke (representative online)
# --------------------------------------------------------------------------- #
def _pick_smoke(integs, t007, n_per=3):
    sus_007 = {iid for iid, o in t007.items() if o.get("citation_valid") is False}
    sus_posts = {i["post_id"] for i in integs
                 for s in i["image_sources"]
                 if s.get("source") == "AUTO-007" and s.get("image_id") in sus_007}
    cats = {
        "no_image": lambda i: not i["has_images"],
        "short_with_image": lambda i: i["has_images"] and i["est_user_tokens"] < 400,
        "long_multi_image": lambda i: i["image_position_count"] >= 5,
        "has_auto007": lambda i: any(s.get("source") == "AUTO-007" for s in i["image_sources"]),
        "has_null_summary": lambda i: any(s.get("summary_present") is False for s in i["image_sources"]),
        "citation_suspicious_affected": lambda i: i["post_id"] in sus_posts,
    }
    picked, seen = [], set()
    for name, pred in cats.items():
        for i in integs:
            if i["post_id"] in seen:
                continue
            if pred(i):
                picked.append((name, i))
                seen.add(i["post_id"])
                if sum(1 for pn, _ in picked if pn == name) >= n_per:
                    break
    return picked


def cmd_smoke(args):
    out = Path(args.out) / "smoke"
    out.mkdir(parents=True, exist_ok=True)
    model, base, key = runner.load_connection()
    params = _effective_params(args)
    params_fp = _params_fp(params)
    ctx = make_ctx(model, base, key, params, params_fp, args.budget,
                   args.concurrency, args.max_retries)
    integs, _, _, t006, t007, _ = build_integrations(model, params, params_fp)
    picked = _pick_smoke(integs, t007, n_per=args.n_per)
    smoke_integs = [i for _, i in picked]
    print("[smoke] model=%s selected=%d categories=%s"
          % (model, len(smoke_integs), sorted({n for n, _ in picked})))
    tee = Tee(out / "smoke.log")
    try:
        runner.run_batch(smoke_integs, ctx, out, resume=not args.no_resume, log=tee)
    finally:
        tee.close()
    results = runner.consolidate(out / "results.jsonl")
    print("[smoke] results:")
    for name, integ in picked:
        rec = results.get(integ["post_id"]) or {}
        calls = rec.get("calls", [])
        usages = [c.get("usage") for c in calls if c.get("usage")]
        tot = sum(u.get("total_tokens", 0) for u in usages)
        print("  %-26s %-22s status=%-24s finish=%s total_tokens=%s"
              % (name, integ["post_id"], rec.get("status"),
                 ",".join(str(c.get("finish_reason")) for c in calls), tot))
    print("[smoke] calibrate max_tokens/budget from the above; see smoke.log for raw.")


# --------------------------------------------------------------------------- #
# run (Phase 2, full)
# --------------------------------------------------------------------------- #
def cmd_run(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    model, base, key = runner.load_connection()
    params = _effective_params(args)
    params_fp = _params_fp(params)
    ctx = make_ctx(model, base, key, params, params_fp, args.budget,
                   args.concurrency, args.max_retries)
    integs, _, _, _, _, _ = build_integrations(model, params, params_fp)
    tee = Tee(out / "run.log")
    try:
        runner.run_batch(integs, ctx, out, resume=not args.no_resume, log=tee)
    finally:
        tee.close()


# --------------------------------------------------------------------------- #
# report (Phase 3, offline)
# --------------------------------------------------------------------------- #
def _cost_rollup(requests_path, results_path):
    calls = []
    p = Path(requests_path)
    if p.is_file():
        with open(p, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        calls.append(json.loads(line))
                    except ValueError:
                        pass
    pt = ct = tt = 0
    pt_known = ct_known = tt_known = False
    usage_missing = 0
    elapsed_sum = 0.0
    elapsed_n = 0
    retries = 0
    chunk_calls = 0
    synth_calls = 0
    for c in calls:
        u = c.get("usage")
        if isinstance(u, dict) and (u.get("prompt_tokens") is not None):
            pt += u.get("prompt_tokens", 0)
            ct += u.get("completion_tokens", 0)
            tt += u.get("total_tokens", 0)
            pt_known = ct_known = tt_known = True
        else:
            usage_missing += 1
        if isinstance(c.get("elapsed_s"), (int, float)):
            elapsed_sum += c["elapsed_s"]
            elapsed_n += 1
        if (c.get("api_attempts") or 1) > 1:
            retries += 1
        tag = c.get("tag") or ""
        if tag.startswith("chunk"):
            chunk_calls += 1
        if tag.startswith("synthesis"):
            synth_calls += 1
    return {
        "total_requests": len(calls),
        "prompt_tokens_sum": pt if pt_known else "unknown",
        "completion_tokens_sum": ct if ct_known else "unknown",
        "total_tokens_sum": tt if tt_known else "unknown",
        "usage_missing_calls": usage_missing,
        "elapsed_s_sum": round(elapsed_sum, 1),
        "elapsed_n": elapsed_n,
        "retry_calls": retries,
        "chunk_calls": chunk_calls,
        "synthesis_calls": synth_calls,
    }


def cmd_report(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    integrations = []
    ip = out / "integration.jsonl"
    if ip.is_file():
        with open(ip, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    integrations.append(json.loads(line))
    results = runner.consolidate(out / "results.jsonl")
    runner.write_final(results, out)

    dataset = compare.build_comparison_dataset(integrations, results)
    compare.write_comparison_jsonl(dataset, out / "comparison_data.jsonl")
    sample = compare.pick_sample(dataset)
    meta_text = ("posts=%d results=%d sample=%d | model/prompt/params recorded in status.json"
                 % (len(integrations), len(results), len(sample)))
    compare.write_comparison_html(sample, meta_text, out / "comparison.html")

    state_counts = Counter(r.get("status") for r in results.values())
    cost = _cost_rollup(out / "requests_log.jsonl", out / "results.jsonl")
    checks = verify.run_checks(out)
    check_summary = verify.summarize(checks)

    report = {
        "phase": "report",
        "total_posts": len(integrations),
        "results": len(results),
        "state_counts": dict(state_counts),
        "cost": cost,
        "verification": check_summary,
        "notes": [
            "usage_missing_calls counted as unknown, not 0",
            "JSON validity / coverage / model confidence are NOT summary accuracy",
            "run-complete != human acceptance; status is REVIEW_READY",
        ],
    }
    (out / "summary_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def cmd_verify(args):
    checks = verify.run_checks(Path(args.out))
    summary = verify.summarize(checks)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    (Path(args.out) / "verification.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(prog="a008")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(sp, online=False):
        sp.add_argument("--out", default=str(config.OUT_DIR))
        sp.add_argument("--max-tokens", type=int, default=config.PARAMS["max_tokens"])
        sp.add_argument("--budget", type=int, default=config.INPUT_TOKEN_BUDGET)
        if online:
            sp.add_argument("--concurrency", type=int, default=config.DEFAULT_CONCURRENCY)
            sp.add_argument("--max-retries", type=int, default=config.MAX_RETRIES)
            sp.add_argument("--no-resume", action="store_true")

    p = sub.add_parser("build"); add_common(p)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("smoke"); add_common(p, online=True)
    p.add_argument("--n-per", type=int, default=3)
    p.set_defaults(func=cmd_smoke)

    p = sub.add_parser("run"); add_common(p, online=True)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("report"); add_common(p)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("verify"); add_common(p)
    p.set_defaults(func=cmd_verify)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
