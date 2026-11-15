from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path, PurePosixPath

from .contracts import IngestionError, JobConfig, digest
from .normalize.legacy import parse

MAX_INPUT_BYTES = 150_000_000


def read_input(path, member=None):
    path = Path(path)
    if member:
        p = PurePosixPath(member)
        if p.is_absolute() or ".." in p.parts or "\\" in member:
            raise IngestionError("unsafe_archive_member")
        with zipfile.ZipFile(path) as archive:
            if len([x for x in archive.namelist() if x == member]) != 1:
                raise IngestionError("missing_or_duplicate_archive_member")
            info = archive.getinfo(member)
            if info.file_size > MAX_INPUT_BYTES:
                raise IngestionError("input_too_large")
            data = archive.read(member)
        with path.open("rb") as stream:
            archive_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        return data, {"archive_sha256": archive_hash, "member": member,
                      "member_sha256": hashlib.sha256(data).hexdigest()}
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise IngestionError("input_too_large")
    data = path.read_bytes()
    return data, {"file_name": path.name, "file_sha256": hashlib.sha256(data).hexdigest()}


def import_bytes(store, content, kind, provenance, *, series_id="", retrieved_at=None, cancelled=None, run_id=None):
    config = JobConfig.parse({"kind": kind, "series_id": series_id}).public()
    config["source_hash"] = hashlib.sha256(content).hexdigest()
    config["retrieved_at"] = retrieved_at
    run_id = store.begin_run(config,run_id)
    task_id = store.task(run_id, kind, digest(provenance))
    material_kind = "product_json" if kind == "product_json" else "legacy_csv"
    response_id = store.response(task_id, content, provenance, retrieved_at, material_kind)
    try:
        def records():
            for record in parse(content, kind, series_id=series_id, retrieved_at=retrieved_at):
                if cancelled and cancelled():
                    raise IngestionError("cancelled")
                yield record
        counts = store.ingest(run_id, task_id, response_id, records())
        status='succeeded' if counts['batch_quality']['passed'] and not any(counts[k] for k in ['conflict','incomplete_skipped','rejected']) else 'partial'
        store.finish_run(run_id, status, counts)
        return {"run_id": run_id, "response_id": response_id, "counts": counts,'status':status,'publishable':status=='succeeded' and counts['review_required']==0}
    except BaseException as error:
        code = error.code if isinstance(error, IngestionError) else "processing_failed"
        store.failure(run_id,task_id,code,snapshot_id=response_id)
        store.finish_run(run_id, "interrupted" if code == "cancelled" or isinstance(error, KeyboardInterrupt) else "failed", {"error_code": code})
        raise


def replay(store, response_id):
    with store.mutex:
        row = store.db.execute("SELECT s.*,s.parse_config_json config_json,s.run_id original_run FROM source_snapshots s WHERE s.snapshot_id=?", (response_id,)).fetchone()
    if not row:
        raise IngestionError("response_not_found")
    import json
    from .contracts import relative_path
    config = json.loads(row["config_json"])
    if row["material_kind"] == "http_body":
        from .normalize.pages import forum_list, post_page, user_page
        from .normalize.author import author_card,attach_card_to_post,merge_card_into_home
        from .normalize.basic import post_id, user_id
        from urllib.parse import urlsplit, parse_qs
        meta = json.loads(row["provenance_json"])
        url = meta["url"]
        content = relative_path(store.root, row["relative_path"]).read_bytes()
        try: text=content.decode('utf-8-sig')
        except UnicodeError: text=content.decode('gb18030')
        if meta.get("http_status") != 200:
            raise IngestionError("cannot_replay_failed_http_response")
        if "GetTopicListPartial2021" in url:
            return {"response_id": response_id, "validated_list_items": len(forum_list(text)), "network_calls": 0}
        if "/listSpec" in url:
            payload = json.loads(text)
            if payload.get("returncode") != 0:
                raise IngestionError("product_source_error")
            return {"response_id": response_id, "validated_spec_index": True, "network_calls": 0}
        if 'getclicksandreplys' in url:
            payload=json.loads(text)
            if not isinstance(payload.get('result'),list): raise IngestionError('interaction_response_invalid')
            return dict(response_id=response_id,validated_interaction_items=len(payload['result']),network_calls=0)
        card_id=None
        for entry in json.loads(row['issues_json']):
            card_id=entry.get('values',{}).get('author_card_snapshot_id') or card_id

        def frozen_card(rid):
            with store.mutex:
                source=store.db.execute('SELECT * FROM source_snapshots WHERE snapshot_id=?',(rid,)).fetchone()
            if not source: raise IngestionError('related_author_card_missing')
            meta=json.loads(source['provenance_json'])
            import re
            match=re.search(r'/getdetailusertpl/(\d+)-[01](?:$|\?)',meta.get('url',''))
            if not match or meta.get('http_status')!=200: raise IngestionError('related_author_card_invalid')
            body=relative_path(store.root,source['relative_path']).read_bytes()
            try: html=body.decode('utf-8-sig')
            except UnicodeError: html=body.decode('gb18030')
            return author_card(html,match[1],source['retrieved_at']),rid
        if "/bbs/thread/" in url:
            hint = None
            with store.mutex:
                lists = store.db.execute("SELECT snapshot_id response_id,provenance_json,relative_path FROM source_snapshots WHERE run_id=?", (row["original_run"],)).fetchall()
            for source in lists:
                if "GetTopicListPartial2021" in json.loads(source["provenance_json"]).get("url", ""):
                    for item in forum_list(relative_path(store.root, source["relative_path"]).read_text(encoding="utf-8-sig")):
                        if item["post_id"] == post_id(url):
                            hint = {**item, "response_id": source["response_id"]}
            records = [post_page(text, post_id(url), url, row["retrieved_at"], hint)]
            for source in lists:
                if 'getclicksandreplys' in json.loads(source['provenance_json']).get('url',''):
                    payload=json.loads(relative_path(store.root,source['relative_path']).read_text(encoding='utf-8-sig'))
                    for stat in payload.get('result',[]):
                        if str(stat.get('topicid'))==post_id(url):
                            records[0].data.update(views=stat.get('views'),replies=stat.get('allreplys',stat.get('replys')))
            if card_id: attach_card_to_post(records[0],*frozen_card(card_id))
        elif '/getdetailusertpl/' in url:
            records=[frozen_card(response_id)[0]]
        elif urlsplit(url).hostname == "i.autohome.com.cn":
            records = [user_page(text, user_id(url), row["retrieved_at"])]
            if card_id: merge_card_into_home(records[0],*frozen_card(card_id))
        elif "/getParamConf" in url:
            from .normalize.legacy import product_json
            sid = parse_qs(urlsplit(url).query).get("seriesid", [""])[0]
            records = list(product_json(content, sid))
        else:
            raise IngestionError("http_replay_adapter_missing")
        run = store.begin_run({"mode": "replay", "response_id": response_id})
        task = store.task(run, "replay", response_id)
        result = store.ingest(run, task, response_id, records)
        store.finish_run(run, "succeeded", result)
        return {"run_id": run, "response_id": response_id, "counts": result, "network_calls": 0}
    return import_bytes(store, relative_path(store.root, row["relative_path"]).read_bytes(), config["kind"],
                        json.loads(row["provenance_json"]), series_id=config["series_id"], retrieved_at=row["retrieved_at"])
