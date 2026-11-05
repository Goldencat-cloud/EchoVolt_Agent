# -*- coding: utf-8 -*-
"""Comparison products (Phase 3, offline): a full per-post comparison dataset
(JSONL) and a self-contained, searchable HTML viewer (embedded stratified
sample) for reviewing original text + image summaries against the final summary.
"""
import json
from pathlib import Path


def _flags(integ):
    sources = integ["image_sources"]
    return {
        "no_image": (not integ["has_images"]),
        "short": (integ["est_user_tokens"] < 400),
        "long_multi_image": (integ["image_position_count"] >= 5),
        "has_auto007": any(s.get("source") == "AUTO-007" for s in sources),
        "has_null_summary": any(s.get("summary_present") is False for s in sources),
        "has_fallback": any(s.get("fallback") for s in sources),
    }


def build_comparison_dataset(integrations, results_by_pid):
    """One dict per post joining the integrated input with the final result."""
    dataset = []
    for integ in integrations:
        pid = integ["post_id"]
        rec = results_by_pid.get(pid) or {}
        parsed = rec.get("parsed") or {}
        flags = _flags(integ)
        flags["citation_suspicious_affected"] = bool(
            rec.get("citation_offending"))
        dataset.append({
            "post_id": pid,
            "source_url": integ.get("source_url"),
            "title": integ.get("title"),
            "status": rec.get("status"),
            "error_code": rec.get("error_code"),
            "chunked": rec.get("chunked", False),
            "num_chunks": rec.get("num_chunks"),
            "flags": flags,
            "sequence": integ["sequence"],
            "image_sources": integ["image_sources"],
            "summary": parsed.get("summary"),
            "key_points": parsed.get("key_points"),
            "uncertainties": parsed.get("uncertainties"),
        })
    return dataset


def write_comparison_jsonl(dataset, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for row in dataset:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return out_path


def pick_sample(dataset, per_flag=12):
    """Stratified sample covering the interesting categories for the HTML view."""
    wanted = ["no_image", "short", "long_multi_image", "has_auto007",
              "has_null_summary", "has_fallback", "citation_suspicious_affected"]
    picked = []
    seen = set()
    # successes first (most useful to eyeball), then failures
    ordered = ([d for d in dataset if d["status"] == "success"]
               + [d for d in dataset if d["status"] != "success"])
    for flag in wanted:
        for d in ordered:
            if d["post_id"] in seen:
                continue
            if d["flags"].get(flag):
                picked.append(d)
                seen.add(d["post_id"])
                if sum(1 for p in picked if p["post_id"] == d["post_id"]) >= 0 and \
                        len([p for p in picked if p["flags"].get(flag)]) >= per_flag:
                    break
    # fill with a spread of successes if under-sized
    if len(picked) < 40:
        for d in ordered:
            if d["post_id"] not in seen and d["status"] == "success":
                picked.append(d)
                seen.add(d["post_id"])
                if len(picked) >= 60:
                    break
    return picked


_HTML = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>AUTO-008 图文整合 · 对照查看器</title>
<style>
body{font-family:-apple-system,Segoe UI,Arial,sans-serif;margin:0;background:#f6f7f9;color:#1a1a1a;}
header{padding:14px 20px;background:#10233b;color:#fff;position:sticky;top:0;z-index:2;}
header h1{margin:0;font-size:18px;}
.bar{padding:10px 20px;background:#fff;border-bottom:1px solid #ddd;display:flex;gap:10px;flex-wrap:wrap;align-items:center;}
.bar input{flex:1;min-width:240px;padding:6px 10px;border:1px solid #bbb;border-radius:6px;}
.badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;background:#e3e8ef;color:#333;margin-left:4px;}
.badge.ok{background:#dff3e3;color:#135a2a;}
.badge.fail{background:#fbe3e3;color:#8a1f1f;}
.list{padding:12px 20px;}
.card{background:#fff;border:1px solid #e0e0e0;border-radius:8px;margin-bottom:10px;overflow:hidden;}
.hd{padding:10px 14px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;}
.hd:hover{background:#fafafa;}
.ttl{font-weight:600;}
.detail{display:none;padding:0 14px 14px;border-top:1px dashed #ccc;}
.detail.open{display:block;}
.seq{border:1px solid #eee;border-radius:6px;padding:10px;margin:8px 0;max-height:420px;overflow:auto;background:#fbfbfb;}
.blk{margin:6px 0;padding:6px 8px;border-left:3px solid #9aa7b8;}
.blk.img{border-left-color:#c9a227;background:#fffdf3;}
.blk.null{opacity:.6;}
.k{font-size:11px;color:#666;font-family:monospace;}
.sum{white-space:pre-wrap;line-height:1.6;}
.kp li,.unc li{margin:3px 0;}
.count{color:#888;font-size:12px;}
</style></head><body>
<header><h1>AUTO-008 · 图文整合与全文摘要对照</h1>
<div class="count" id="meta"></div></header>
<div class="bar"><input id="q" placeholder="搜索 post_id / 标题 / 关键词…" oninput="filter()"></div>
<div class="list" id="list"></div>
<script>
const DATA = __SAMPLE__;
document.getElementById('meta').textContent = META_TEXT;
function esc(s){return (s==null?'':String(s)).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function badges(d){
  let h='<span class="badge '+(d.status==='success'?'ok':'fail')+'">'+esc(d.status||'unknown')+'</span>';
  for(const k in d.flags){ if(d.flags[k]) h+='<span class="badge">'+esc(k)+'</span>'; }
  return h;
}
function renderSeq(seq){
  if(!seq||!seq.length) return '<div class="blk">（空序列）</div>';
  return seq.map(b=>{
    if(b.type==='text'){
      return '<div class="blk"><div class="k">TEXT '+esc(b.text_block_id)+'</div>'+
             '<div class="sum">'+esc(b.text)+'</div></div>';
    }
    const cls='blk img'+(b.image_id==null||b.summary==null?' null':'');
    return '<div class="'+cls+'"><div class="k">IMAGE '+esc(b.image_id||'(unmapped)')+
           '</div><div class="sum">'+(b.summary==null?'<em>(summary=null)</em>':esc(b.summary))+
           '</div></div>';
  }).join('');
}
function renderKP(kps,unc){
  let h='';
  if(kps&&kps.length){h+='<div><b>key_points</b><ul class="kp">'+kps.map(k=>
    '<li>'+esc(k.point)+' <span class="k">['+esc((k.basis||''))+
    '] T:'+esc((k.text_block_ids||[]).join(','))+' IMG:'+esc((k.image_ids||[]).join(','))+
    '</span></li>').join('')+'</ul></div>';}
  if(unc&&unc.length){h+='<div><b>uncertainties</b><ul class="unc">'+unc.map(u=>
    '<li>'+esc(u.issue)+' <span class="k">T:'+esc((u.text_block_ids||[]).join(','))+
    ' IMG:'+esc((u.image_ids||[]).join(','))+'</span></li>').join('')+'</ul></div>';}
  return h||'<div class="count">（无 key_points / uncertainties）</div>';
}
function render(){
  const el=document.getElementById('list'); el.innerHTML='';
  DATA.forEach((d,i)=>{
    const card=document.createElement('div');card.className='card';
    card.innerHTML='<div class="hd"><div><span class="ttl">'+esc(d.title||'(无标题)')+
      '</span> <span class="k">'+esc(d.post_id)+'</span></div><div>'+badges(d)+'</div></div>'+
      '<div class="detail"><div class="count">原文序列（'+(d.sequence?d.sequence.length:0)+' 块）</div>'+
      renderSeq(d.sequence)+
      '<div class="count">最终摘要</div><div class="sum">'+esc(d.summary||'(无)')+'</div>'+
      renderKP(d.key_points,d.uncertainties)+
      (d.source_url?'<div class="k"><a href="'+esc(d.source_url)+'" target="_blank">原帖链接</a></div>':'')+
      '</div>';
    card.querySelector('.hd').onclick=function(){
      card.querySelector('.detail').classList.toggle('open');};
    el.appendChild(card);
  });
}
function filter(){
  const q=document.getElementById('q').value.trim().toLowerCase();
  document.querySelectorAll('.card').forEach((c,idx)=>{
    const d=DATA[idx];
    const hay=((d.post_id||'')+' '+(d.title||'')+' '+(d.summary||'')).toLowerCase();
    c.style.display=(!q||hay.indexOf(q)>=0)?'':'none';
  });
}
render();
</script></body></html>
"""


def write_comparison_html(sample, meta_text, out_path):
    payload = json.dumps(sample, ensure_ascii=False).replace("</", "<\\/")
    html = (_HTML.replace("__SAMPLE__", payload)
                .replace("META_TEXT", json.dumps(meta_text, ensure_ascii=False)))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
