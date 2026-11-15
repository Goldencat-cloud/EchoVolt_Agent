# -*- coding: utf-8 -*-
"""Before/after comparison + offline stratified evaluation for AUTO-007.

Compares the AUTO-006 image-only baseline (before) with the context-enhanced
re-analysis (after), per image. Emits a per-image JSONL/CSV and a standalone
local HTML viewer (distinct filename + distinct localStorage key, so it never
overwrites the existing human removal-review page or its stored marks).

The 100 human labels (81 removable / 11 retain / 8 doubtful) are used ONLY as an
offline stratification axis; they are never sent to the model. These comparisons
are triage heuristics, not accuracy metrics -- a change does not imply an
improvement, and enhanced quality still requires NEW human judgment.
"""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from . import config

# Human-label vocabulary (offline stratification only; never model input).
LABEL_MAP = {"pass": "removable", "fail": "retain", "doubt": "doubtful"}
TEXT_ONLY_MARKERS = ("仅文字", "无可见证据", "文字线索", "仅凭帖子", "文字提到")

# Distinct store key + filename so this page never collides with the human
# removal-review page (store 'irrelevant-removal-review-20261010-n100-s20261010').
STORE_KEY = "auto-007-before-after-review-20261010"
HTML_FILENAME = "auto-007_before_after_comparison.html"


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
def load_qc_labels(path=config.QC_REVIEWS_JSON):
    """Return ``{image_id: label}`` (removable/retain/doubtful) from the QC JSON.

    Read-only. Raises if the file is missing (a hard precondition for the
    stratified eval; the before/after comparison itself does not require it).
    """
    d = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    marks = d.get("marks") or {}
    out = {}
    for iid, m in marks.items():
        lab = LABEL_MAP.get(m.get("v"))
        if lab:
            out[iid] = lab
    return out


def load_after(after_final_path):
    """Return ``{image_id: record}`` from the consolidated after results."""
    from . import runner
    return runner.consolidate(after_final_path)


# --------------------------------------------------------------------------- #
# Per-image comparison
# --------------------------------------------------------------------------- #
def _topics(parsed):
    ev = (parsed or {}).get("potential_evidence_value") or []
    topics = []
    for item in ev:
        if isinstance(item, dict) and isinstance(item.get("topic"), str):
            topics.append(item["topic"].strip())
    return topics


def _ident(parsed):
    vi = (parsed or {}).get("vehicle_identification") or {}
    return {
        "brand": vi.get("brand"),
        "model": vi.get("model"),
        "basis": vi.get("identification_basis"),
    }


def _ident_category(ident):
    """Classify identification basis (triage heuristic, not ground truth)."""
    if not ident.get("brand") and not ident.get("model"):
        return "no_identification"
    basis = ident.get("basis") or ""
    if any(marker in basis for marker in TEXT_ONLY_MARKERS):
        return "text_only_clue"
    if basis:
        return "image_basis"
    return "identified_no_basis"


def compare_one(image_id, before_entry, after_rec):
    before_parsed = (before_entry or {}).get("before_parsed") or {}
    after = {}
    status = "missing"
    if after_rec is not None:
        status = after_rec.get("status")
        if status == "success":
            after = after_rec.get("parsed") or {}

    b_it = before_parsed.get("image_type")
    a_it = after.get("image_type")
    a_sum = after.get("summary") or ""
    b_ident = _ident(before_parsed)
    a_ident = _ident(after)
    a_ca = after.get("context_assessment") or {}
    rounds = (after_rec or {}).get("rounds") or []
    elapsed = round(sum(r.get("elapsed_s") or 0 for r in rounds), 3)
    usage = {}
    for r in rounds:
        u = r.get("usage") or {}
        for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if isinstance(u.get(k), int):
                usage[k] = usage.get(k, 0) + u[k]

    ident_changed = (b_ident["brand"], b_ident["model"]) != (a_ident["brand"], a_ident["model"])
    return {
        "image_id": image_id,
        "status": status,
        "before_image_type": b_it,
        "after_image_type": a_it,
        "image_type_changed": (a_it is not None and b_it is not None and a_it != b_it),
        "before_summary": before_parsed.get("summary"),
        "after_summary": a_sum or None,
        "mentions_post_text": ("帖子文字称" in a_sum) if a_sum else False,
        "before_brand": b_ident["brand"],
        "before_model": b_ident["model"],
        "after_brand": a_ident["brand"],
        "after_model": a_ident["model"],
        "identification_changed": ident_changed,
        "after_ident_category": (_ident_category(a_ident) if status == "success" else None),
        "before_topics": _topics(before_parsed),
        "after_topics": _topics(after),
        "evidence_topics_changed": (sorted(set(_topics(before_parsed))) !=
                                    sorted(set(_topics(after)))) if status == "success" else None,
        "context_relevance": a_ca.get("context_relevance") if status == "success" else None,
        "expansion_applied": bool(((after_rec or {}).get("context") or {}).get("applied")),
        "citation_valid": (after_rec or {}).get("citation_valid"),
        "api_elapsed_s": elapsed,
        "usage": usage,
        "error_code": (after_rec or {}).get("error_code"),
    }


def build_comparison(before_index, after_by_id):
    """Per-image comparison rows for every before image (ordered by image_id)."""
    rows = []
    for iid in sorted(before_index):
        rows.append(compare_one(iid, before_index[iid], after_by_id.get(iid)))
    return rows


# --------------------------------------------------------------------------- #
# Outputs (JSONL + CSV)
# --------------------------------------------------------------------------- #
_CSV_FIELDS = [
    "image_id", "status", "before_image_type", "after_image_type",
    "image_type_changed", "mentions_post_text", "before_brand", "before_model",
    "after_brand", "after_model", "identification_changed", "after_ident_category",
    "context_relevance", "expansion_applied", "citation_valid", "api_elapsed_s",
    "error_code",
]


def write_comparison_outputs(rows, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    jpath = out_dir / "comparison.jsonl"
    with open(jpath, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    cpath = out_dir / "comparison.csv"
    with open(cpath, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(_CSV_FIELDS)
        for r in rows:
            writer.writerow([r.get(f, "") for f in _CSV_FIELDS])
    return jpath, cpath


# --------------------------------------------------------------------------- #
# Offline stratified evaluation (labels are NOT sent to the model)
# --------------------------------------------------------------------------- #
def _group_stats(subset):
    n = len(subset)
    if not n:
        return {"n": 0}
    def frac(pred):
        return round(100.0 * sum(1 for r in subset if pred(r)) / n, 2)
    success = [r for r in subset if r.get("status") == "success"]
    return {
        "n": n,
        "success": len(success),
        "failed": n - len(success),
        "image_type_changed_pct": frac(lambda r: r.get("image_type_changed")),
        "mentions_post_text_pct": frac(lambda r: r.get("mentions_post_text")),
        "identification_changed_pct": frac(lambda r: r.get("identification_changed")),
        "expansion_applied_pct": frac(lambda r: r.get("expansion_applied")),
        "context_relevance_counts": _count(lambda r: r.get("context_relevance"), subset),
        "note": "triage heuristics, not accuracy; change != improvement",
    }


def _count(field_fn, subset):
    out = {}
    for r in subset:
        v = field_fn(r)
        if v is not None:
            out[v] = out.get(v, 0) + 1
    return out


def stratified_eval(rows, qc_labels):
    """Group the 100 labeled images into removable/retain/doubtful and report
    before/after stats per group. Labels are used offline only."""
    by_label = {"removable": [], "retain": [], "doubtful": []}
    for r in rows:
        lab = qc_labels.get(r["image_id"])
        if lab in by_label:
            by_label[lab].append(r)
    groups = {lab: _group_stats(subset) for lab, subset in by_label.items()}
    labeled_rows = [r for r in rows if r["image_id"] in qc_labels]
    return {
        "generated_at": _utcnow_iso(),
        "labels_used": "offline stratification only; NOT sent to model",
        "label_source": str(config.QC_REVIEWS_JSON),
        "labeled_subset_size": len(labeled_rows),
        "label_counts": {lab: len(v) for lab, v in by_label.items()},
        "groups": groups,
        "verifiable_cases_note": (
            "A case is 'verifiable' when the human label and the after judgment "
            "address the same question (e.g. removable label vs context_relevance=无关)."
        ),
    }


# --------------------------------------------------------------------------- #
# Standalone local HTML viewer (distinct store key + filename)
# --------------------------------------------------------------------------- #
_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AUTO-007 前后对比</title>
<style>
:root{--bg:#0f1115;--panel:#171a21;--ink:#e6e9ef;--mut:#9aa3b2;--accent:#5b9cff;
--ok:#38c793;--warn:#f5b942;--err:#f2637b;--line:#262b36;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;padding:20px}
h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--mut);margin-bottom:16px;font-size:13px}
.bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:14px}
select,button{background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:7px 10px;font-size:13px}
.stat{color:var(--mut);font-size:13px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:14px}
.head{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px}
.id{font-family:ui-monospace,Consolas,monospace;color:var(--accent);font-size:12px;word-break:break-all}
.tag{font-size:12px;border-radius:20px;padding:2px 9px;border:1px solid var(--line);color:var(--mut)}
.tag.ok{color:var(--ok);border-color:rgba(56,199,147,.4)}
.tag.warn{color:var(--warn);border-color:rgba(245,185,66,.4)}
.tag.err{color:var(--err);border-color:rgba(242,99,123,.4)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:760px){.cols{grid-template-columns:1fr}}
.col h3{font-size:12px;color:var(--mut);margin:0 0 6px;text-transform:uppercase;letter-spacing:.04em}
.sum{white-space:pre-wrap;word-break:break-word;font-size:13px}
.kv{color:var(--mut);font-size:12px;margin-top:8px}
.kv b{color:var(--ink);font-weight:600}
.imgwrap{margin-top:10px;text-align:center}
.imgwrap img{max-width:100%;max-height:420px;border-radius:8px;border:1px solid var(--line)}
.qbtns{margin-top:10px;display:flex;gap:8px;flex-wrap:wrap}
.qbtns button.sel{border-color:var(--accent);color:var(--accent)}
.hidden{display:none}
.note{color:var(--mut);font-size:12px;margin-top:4px}
</style>
</head>
<body>
<h1>AUTO-007 · 前后对比（图片-only → 图片+帖子上下文）</h1>
<div class="sub" id="meta"></div>
<div class="bar">
<select id="fLabel"><option value="">标签组：全部</option><option value="removable">removable(81)</option><option value="retain">retain(11)</option><option value="doubtful">doubtful(8)</option><option value="__none__">未抽样(其余)</option></select>
<select id="fType"><option value="">类型变化：全部</option><option value="changed">已变化</option><option value="unchanged">未变化</option></select>
<select id="fRel"><option value="">context_relevance：全部</option><option value="有关">有关</option><option value="无关">无关</option><option value="证据不足">证据不足</option></select>
<button id="reset">重置筛选</button>
<span class="stat" id="stat"></span>
</div>
<div id="list"></div>
<script>
const DATA=__DATA__;
const IMGROOT=__IMGROOT__;
const STORE=__STORE__;
const listEl=document.getElementById('list');
const statEl=document.getElementById('stat');
const metaEl=document.getElementById('meta');
metaEl.textContent=DATA.meta||'';
const saved=JSON.parse(localStorage.getItem(STORE)||'{}');
function esc(s){return (s==null?'':'').toString().replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function tag(txt,cls){return '<span class="tag '+ (cls||'') +'">'+esc(txt)+'</span>';}
function render(){
 const fl=document.getElementById('fLabel').value;
 const ft=document.getElementById('fType').value;
 const fr=document.getElementById('fRel').value;
 const rows=DATA.rows.filter(r=>{
  const lab=r.label||'__none__';
  if(fl&&lab!==fl)return false;
  if(ft==='changed'&&!(r.image_type_changed===true))return false;
  if(ft==='unchanged'&&(r.image_type_changed===true))return false;
  if(fr&&(r.context_relevance||'__na__')!==fr)return false;
  return true;
 });
 statEl.textContent='显示 '+rows.length+' / '+DATA.rows.length;
 listEl.innerHTML='';
 rows.forEach(r=>{
  const card=document.createElement('div');card.className='card';
  const stCls=r.status==='success'?'ok':'err';
  const changed=r.image_type_changed===true;
  let h='<div class="head">'
   +'<span class="id">'+esc(r.image_id)+'</span>'
   +tag(r.status,stCls)
   +(r.label?tag(r.label,'warn'):tag('未抽样'))
   +tag('type:'+(r.before_image_type||'?')+' → '+(r.after_image_type||'?'),changed?'ok':'')
   +(r.expansion_applied?tag('扩展','warn'):'')
   +(r.citation_valid===false?tag('引用存疑','err'):'')
   +'</div>';
  h+='<div class="cols">';
  h+='<div class="col"><h3>BEFORE · 仅图片 (AUTO-006)</h3>'
   +'<div class="sum">'+esc(r.before_summary||'(无)')+'</div>'
   +'<div class="kv">识别: <b>'+esc(r.before_brand||'-')+'/'+esc(r.before_model||'-')+'</b> · 主题: <b>'+esc((r.before_topics||[]).join(', ')||'-')+'</b></div></div>';
  h+='<div class="col"><h3>AFTER · 图片+上下文</h3>'
   +'<div class="sum">'+esc(r.after_summary||('(无 / '+esc(r.status)+')') )+'</div>'
   +'<div class="kv">识别: <b>'+esc(r.after_brand||'-')+'/'+esc(r.after_model||'-')+'</b> · 类别: <b>'+esc(r.after_ident_category||'-')+'</b><br>'
   +'context_relevance: <b>'+esc(r.context_relevance||'-')+'</b> · 引用校验: <b>'+esc(String(r.citation_valid))+'</b> · 耗时: <b>'+esc(r.api_elapsed_s)+'s</b></div></div>';
  h+='</div>';
  const imgSrc=IMGROOT.replace(/\\\\/g,'/')+'/'+(r.relpath||'').replace(/\\\\/g,'/');
  h+='<div class="imgwrap"><img loading="lazy" src="'+esc(imgSrc)+'" onerror="this.style.display=\'none\'"></div>';
  const q=['有关','无关','证据不足','需再看'];
  h+='<div class="qbtns">'+q.map(x=>{
    const cur=saved[r.image_id];
    return '<button data-id="'+esc(r.image_id)+'" data-v="'+x+'" class="'+(cur===x?'sel':'')+'">'+x+'</button>';
  }).join('')+'</div>';
  h+='<div class="note">此页仅用于对“增强后质量”做新的独立人工判断；不与既有删除评审页共用存储。</div>';
  card.innerHTML=h;
  card.querySelectorAll('.qbtns button').forEach(btn=>{
   btn.onclick=()=>{const id=btn.dataset.id,v=btn.dataset.v;
     if(saved[id]===v)delete saved[id];else saved[id]=v;
     localStorage.setItem(STORE,JSON.stringify(saved));
     card.querySelectorAll('.qbtns button').forEach(b=>b.classList.toggle('sel',b.dataset.v===saved[id]));
   };
  });
  listEl.appendChild(card);
 });
}
['fLabel','fType','fRel'].forEach(id=>document.getElementById(id).onchange=render);
document.getElementById('reset').onclick=()=>{['fLabel','fType','fRel'].forEach(id=>document.getElementById(id).value='');render();};
render();
</script>
</body>
</html>
"""


def render_html(rows, qc_labels, before_index, meta, out_path):
    """Write a standalone before/after viewer. Distinct filename + store key."""
    enriched = []
    for r in rows:
        rr = dict(r)
        rr["label"] = qc_labels.get(r["image_id"])
        rr["relpath"] = (before_index.get(r["image_id"]) or {}).get("relpath")
        enriched.append(rr)
    data = {"meta": meta, "rows": enriched}
    html = _HTML_TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    html = html.replace("__IMGROOT__", json.dumps(str(config.IMG_ROOT)))
    html = html.replace("__STORE__", json.dumps(STORE_KEY))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
