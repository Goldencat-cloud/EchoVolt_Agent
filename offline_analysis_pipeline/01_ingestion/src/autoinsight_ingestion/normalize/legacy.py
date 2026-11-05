"""Explicit adapters for supplied historical exports; no imported legacy scripts."""
from __future__ import annotations

import csv
import io
import json
import re
from collections import OrderedDict

from ..contracts import IngestionError, Record, canonical, digest
from ..quality import evaluate
from .basic import clean_text, number, parse_time, post_id, user_id

csv.field_size_limit(10_000_000)


def pick(row, *names):
    return next((row[n] for n in names if row.get(n) not in (None, "")), "")


def json_value(value, default):
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def csv_rows(content):
    try:
        text = content.decode("utf-8-sig")
    except UnicodeError:
        raise IngestionError("csv_encoding_not_utf8") from None
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise IngestionError("invalid_csv_header")
    for row in reader:
        if None in row:
            raise IngestionError("csv_column_count_mismatch")
        yield reader.line_num, row


def segments(row):
    full = pick(row, "全文", "multimodal_content")
    value = json_value(full, None)
    output = []
    if isinstance(value, list):
        valid = True
        for i, item in enumerate(value):
            if isinstance(item, (list, tuple)) and len(item) == 2:
                kind, text = item
            elif isinstance(item, dict):
                kind = item.get("type")
                text = item.get("text") or item.get("url") or item.get("content") or item.get("value")
            else:
                valid = False
                continue
            kind = {"img": "image", "vid": "video"}.get(kind, kind)
            if kind not in {"text", "image", "video"} or not isinstance(text, str):
                valid = False
                continue
            output.append({"kind": kind, "value": text, "locator": f"sequence[{i}]"})
        if valid and output:
            return output, "ordered"
    body = pick(row, "正文", "text_content", "clean_text")
    output = [{"kind": "text", "value": body, "locator": "body"}] if body else []
    for field, kind in [(pick(row, "图片链接", "images"), "image"), (pick(row, "视频ID", "video_ids"), "video")]:
        values = json_value(field, None)
        if not isinstance(values, list):
            values = [s.strip() for s in str(field).split("|") if s.strip()]
        for value in values:
            if isinstance(value, str):
                output.append({"kind": kind, "value": value, "locator": "unordered_reference"})
    return output, "media_order_unknown"


def posts(content, retrieved_at=None):
    for line, row in csv_rows(content):
        url = pick(row, "帖子链接", "source_url", "字段1_链接")
        source_id = post_id(url)
        supplied_id = str(row.get("post_id") or "")
        issues = []
        if supplied_id and source_id and supplied_id != source_id:
            issues.append("post_id_conflict")
        sequence, sequence_status = segments(row)
        raw = pick(row, "正文", "text_content") or "\n".join(s["value"] for s in sequence if s["kind"] == "text")
        author_home = pick(row, "作者主页", "author_home", "作者主页_列表页")
        data = {"post_id": source_id or supplied_id, "source_url": url,
                "title": pick(row, "帖子标题", "title", "字段1_文本"),
                "text_content": raw, "clean_text": clean_text(raw), "segments": sequence,
                "sequence_status": sequence_status, "author_home": author_home,
                "user_id": user_id(author_home), "author_nick": pick(row, "作者昵称", "author_nick", "作者昵称_列表页"),
                "time": parse_time(pick(row, "发布时间", "created_at", "帖子相对时间"), retrieved_at),
                "views": number(re.sub(r"\s*(?:浏览|阅读)$", "", pick(row, "浏览数", "views"))),
                "replies": number(re.sub(r"\s*(?:回帖|回复)$", "", pick(row, "回帖数", "replies")))}
        data.update(list_time_raw=row.get('帖子相对时间'), list_image_count=number(row.get('列表图片数')),
                    tags=[t.strip() for t in re.split(r"[|,，/]", str(row.get('帖子标签') or "")) if t.strip()],
                    list_author_nickname=row.get('作者昵称_列表页'), list_author_home_url=row.get('作者主页_列表页'),
                    author_context={k: row.get(v) for k,v in AUTHOR_CONTEXT.items() if v in row},
                    field_availability={})
        rec=Record("posts", data["post_id"], data, f"csv-line:{line}", issues, "post_id_conflict" in issues)
        rec.audit={'legacy_body_match_status':row.get('是否匹配正文')}
        yield evaluate(rec)


def users(content):
    for line, row in csv_rows(content):
        source_id = str(row.get("user_id") or "")
        sex_source = row.get("sex_source", "")
        raw = row.get("sex_raw", "")
        explicit = {"1": "男", "2": "女"}.get(raw) if sex_source == "hdsex" else None
        data = {"source_url": row.get("home_url"), "nickname": row.get("nickname"), "sex_raw": raw,
                "sex_explicit": explicit, "sex_inferred": row.get("sex_label") if str(sex_source).startswith("pronoun") else None,
                "sex_source": sex_source, "following": number(row.get("following")), "followers": number(row.get("followers")),
                "ip_location": row.get("ip_location"), "csv_location": row.get("csv_location"),
                "fetched_at": row.get("fetched_at"), "status": row.get("status", "unknown")}
        rec=Record("users", source_id, data, f"csv-line:{line}")
        rec.audit={'legacy_error':row.get('error'), 'legacy_dataset_post_count':row.get('post_count_in_dataset'),
                   'sex_label_raw':row.get('sex_label')}
        yield evaluate(rec)


def series(content):
    for line, row in csv_rows(content):
        yield evaluate(Record("series", str(row.get("seriesId") or ""),
                              {"brand_name": row.get("品牌"), "series_name": row.get("车系名"),
                               "manufacturer_name":row.get('厂商'),"vehicle_class":row.get('级别'),'guide_price_range_raw':row.get('指导价'),
                               'initial_letter':row.get('字母')}, f"csv-line:{line}"))


AUTHOR_CONTEXT = {'platform_post_count':'作者帖子数','popular_post_count':'作者热门帖数',
                  'platform_reply_count':'作者回复数','registered_at_raw':'作者注册时间',
                  'declared_location':'作者来自','declared_vehicle':'作者爱车','popular_post_urls_raw':'作者热门帖链接'}


def models(content, series_id):
    if not str(series_id).isdigit(): raise IngestionError('series_id_required')
    for line,row in csv_rows(content):
        data=dict(series_id=series_id,spec_name=row.get('车型名称'),model_year=row.get('年款'),
                  sale_status_raw=row.get('状态'),is_concept=bool(re.search('猜想|概念|原型',row.get('车型名称',''))),
                  list_price_raw=row.get('厂商指导价'),dealer_price_raw=row.get('经销商报价'),
                  model_group=row.get('车型组'),
                  condition_tags=[t.strip() for t in re.split(r"[/|,，]", str(row.get('条件标签') or "")) if t.strip()],
                  sale_status_code=row.get('specstatus'),parameters=[])
        rec=Record('parameters',str(row.get('specid') or ''),data,f'csv-line:{line}')
        rec.audit={'sale_status_code':row.get('specstatus')}
        yield evaluate(rec)


def parameters(content, series_id):
    if not str(series_id).isdigit():
        raise IngestionError("series_id_required")
    groups = OrderedDict()
    for line, row in csv_rows(content):
        sid = str(row.get("specid") or "")
        if sid not in groups:
            groups[sid] = {"line": line, "rows": [], "parameters": []}
        groups[sid]["rows"].append(row)
        groups[sid]["parameters"].append({"source_item_key": digest([row.get("配置分组"), row.get("配置分类"), row.get("配置项"), line]),
                                       "group_name": row.get("配置分组"), "category": row.get("配置分类"),
                                       "name": row.get("配置项"), "raw_value": row.get("配置值"), "source_locator": f"csv-line:{line}"})
    for sid, group in groups.items():
        row = group["rows"][0]
        name = row.get("车型名称", "")
        data = {"series_id": series_id, "spec_name": name, "model_year": row.get("年款") or None,
                "sale_status_raw": row.get("状态"), "is_concept": bool(re.search("猜想|概念|原型", name)),
                "parameters": group["parameters"]}
        yield evaluate(Record("parameters", sid, data, f"csv-line:{group['line']}", ["parameter_key_fallback"]))


def product_list(content):
    """Parse a listSpec response into specid -> price/group/status metadata fields."""
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (ValueError, UnicodeError):
        raise IngestionError("invalid_product_json") from None
    if payload.get("returncode") != 0 or not isinstance(payload.get("result"), dict):
        raise IngestionError("product_source_error")
    result = payload["result"]
    meta = {}
    for group in (result.get("list") or []) + (result.get("otherlist") or []):
        for item in group.get("speclist") or []:
            sid = str(item.get("id") or "")
            if not sid.isdigit():
                continue
            if sid in meta:
                raise IngestionError("duplicate_response_spec_id")
            tags = []
            if str(item.get("iselectric")) == "1":
                tags.append("electric")
            if str(item.get("iswaitsell")) == "1":
                tags.append("wait_sell")
            meta[sid] = {"model_group": clean_text(group.get("name")) or None,
                         "list_price_raw": clean_text(item.get("price")) or None,
                         "condition_tags": tags or None}
    return meta


def product_json(content, series_id, spec_meta=None):
    if not str(series_id).isdigit():
        raise IngestionError("series_id_required")
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (ValueError, UnicodeError):
        raise IngestionError("invalid_product_json") from None
    if payload.get("returncode") != 0 or not isinstance(payload.get("result"), dict):
        raise IngestionError("product_source_error")
    result = payload["result"]
    meta = {}
    for gi, group in enumerate(result.get("titlelist") or []):
        for ii, item in enumerate(group.get("items") or []):
            tid = item.get("titleid")
            if tid in meta:
                raise IngestionError("duplicate_response_title_id")
            meta[tid] = (gi, ii, group, item)
    for index, model in enumerate(result.get("datalist") or []):
        values, issues = [], []
        for value in model.get("paramconflist") or []:
            if value.get("titleid") not in meta:
                issues.append("parameter_title_missing")
                continue
            gi, ii, group, item = meta[value["titleid"]]
            key = [group.get("groupname"), group.get("itemtype"), item.get("itemid"), item.get("itemname")]
            if item.get("itemid") is None:
                key += [gi, ii]
                issues.append("parameter_key_fallback")
            values.append({"source_item_key": digest(key), "group_name": group.get("groupname"),
                           "category": group.get("itemtype"), "name": item.get("itemname"),
                           "raw_value": str(value.get("itemname") or ""), "source_value": value})
        name = str(model.get("specname") or "")
        year = re.search(r"(20\d{2})\s*款", name)
        data = {"series_id": series_id, "spec_name": name, "model_year": year[1] if year else None,
                "sale_status_raw": str(model.get("specstatus")), "is_concept": bool(re.search("猜想|概念|原型", name)),
                "parameters": values}
        if spec_meta:
            data.update(spec_meta.get(str(model.get("specid") or ""), {}))
        yield evaluate(Record("parameters", str(model.get("specid") or ""), data, f"result.datalist[{index}]", issues))


def parse(content, kind, *, series_id="", retrieved_at=None):
    if kind != 'product_json':
        from ..field_contract import validate_columns
        header=next(csv.reader(io.StringIO(content.decode('utf-8-sig'))),[])
        validate_columns(header,kind)
    if kind == "posts":
        return posts(content, retrieved_at)
    if kind == "users":
        return users(content)
    if kind == "series":
        return series(content)
    if kind == "models":
        return models(content,series_id)
    if kind == "parameters":
        return parameters(content, series_id)
    if kind == "product_json":
        return product_json(content, series_id)
    raise IngestionError("unsupported_kind")
