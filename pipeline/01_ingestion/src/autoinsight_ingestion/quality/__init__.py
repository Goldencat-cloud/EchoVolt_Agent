"""Versioned basic readiness evaluation, not semantic acceptance."""


def evaluate(record):
    if not record.source_id or not record.source_id.isdigit():
        record.rejected = True
        record.issues.append("identity_missing_or_invalid")
    if record.kind == "posts":
        if not record.data.get("text_content", "").strip():
            record.issues.append("body_empty_or_unverified")
        if record.data.get("sequence_status") != "ordered":
            record.issues.append("media_order_unknown")
        if record.data.get("time", {}).get("value") is None:
            record.issues.append("publication_time_unknown")
    if record.kind == "users" and record.data.get("status") != "ok":
        record.issues.append("profile_fetch_not_ok")
    record.issues = sorted(set(record.issues))
    return record
