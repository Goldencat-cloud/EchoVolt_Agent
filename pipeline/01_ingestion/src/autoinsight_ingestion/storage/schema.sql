-- Database v2: eight tables. Runtime records and data quality are separate.
CREATE TABLE collection_runs (
 run_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE, request_hash TEXT,
 request_json TEXT NOT NULL DEFAULT '{}', config_json TEXT NOT NULL,
 state TEXT NOT NULL, execution_count INTEGER NOT NULL DEFAULT 1,
 cancel_requested INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
 started_at TEXT, updated_at TEXT NOT NULL, finished_at TEXT,
 counts_json TEXT NOT NULL DEFAULT '{}', result_json TEXT, error_code TEXT,
 attempts_json TEXT NOT NULL DEFAULT '[]', audit_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE source_snapshots (
 snapshot_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES collection_runs,
 sha256 TEXT NOT NULL, relative_path TEXT NOT NULL, byte_count INTEGER NOT NULL,
 retrieved_at TEXT, material_kind TEXT NOT NULL, provenance_json TEXT NOT NULL,
 parse_config_json TEXT NOT NULL, parse_state TEXT NOT NULL DEFAULT 'pending',
 issues_json TEXT NOT NULL DEFAULT '[]', summary_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE posts (
 post_id TEXT PRIMARY KEY, source_url TEXT, title TEXT, body_text TEXT, clean_text TEXT,
 author_id TEXT, author_nickname TEXT, author_home_url TEXT,
 published_at TEXT, published_raw TEXT, time_precision TEXT, time_basis TEXT,
 view_count NUMERIC, reply_count NUMERIC, list_time_raw TEXT, list_image_count NUMERIC,
 tags_json TEXT, list_author_nickname TEXT, list_author_home_url TEXT,
 content_segments_json TEXT NOT NULL, content_order_status TEXT,
 author_context_json TEXT NOT NULL DEFAULT '{}', field_availability_json TEXT NOT NULL DEFAULT '{}',
 snapshot_id TEXT NOT NULL REFERENCES source_snapshots, source_locator TEXT NOT NULL,
 retrieved_at TEXT, parser_version TEXT NOT NULL, cleaner_version TEXT NOT NULL,
 quality_version TEXT NOT NULL, quality_state TEXT NOT NULL,
 issues_json TEXT NOT NULL, record_hash TEXT NOT NULL, retained_fields_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE users (
 user_id TEXT PRIMARY KEY, home_url TEXT, nickname TEXT, sex_raw TEXT,
 sex_explicit TEXT, sex_inferred TEXT, sex_source TEXT, following_count NUMERIC,
 follower_count NUMERIC, ip_location TEXT, declared_location TEXT,
 profile_status TEXT, profile_fetched_at TEXT, registered_at TEXT,
 platform_post_count NUMERIC, popular_post_count NUMERIC, platform_reply_count NUMERIC,
 declared_vehicle TEXT, popular_post_urls_json TEXT, field_availability_json TEXT NOT NULL DEFAULT '{}',
 snapshot_id TEXT NOT NULL REFERENCES source_snapshots, source_locator TEXT NOT NULL,
 retrieved_at TEXT, parser_version TEXT NOT NULL, cleaner_version TEXT NOT NULL,
 quality_version TEXT NOT NULL, quality_state TEXT NOT NULL,
 issues_json TEXT NOT NULL, record_hash TEXT NOT NULL, retained_fields_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE product_specs (
 spec_id TEXT PRIMARY KEY, series_id TEXT NOT NULL, brand_name TEXT, series_name TEXT, manufacturer_name TEXT,
 spec_name TEXT, model_year TEXT, sale_status_raw TEXT, is_concept INTEGER,
 list_price_raw TEXT, dealer_price_raw TEXT, model_group TEXT, condition_tags_json TEXT, sale_status_code TEXT,
 snapshot_id TEXT NOT NULL REFERENCES source_snapshots, source_locator TEXT NOT NULL,
 retrieved_at TEXT, parser_version TEXT NOT NULL, cleaner_version TEXT NOT NULL,
 quality_version TEXT NOT NULL, quality_state TEXT NOT NULL,
 issues_json TEXT NOT NULL, record_hash TEXT NOT NULL, retained_fields_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE product_parameters (
 spec_id TEXT NOT NULL REFERENCES product_specs, source_item_key TEXT NOT NULL,
 group_name TEXT, category TEXT, parameter_name TEXT, value_raw TEXT, source_value_json TEXT,
 snapshot_id TEXT NOT NULL REFERENCES source_snapshots, source_locator TEXT NOT NULL,
 retrieved_at TEXT, parser_version TEXT NOT NULL, cleaner_version TEXT NOT NULL,
 quality_version TEXT NOT NULL, quality_state TEXT NOT NULL,
 issues_json TEXT NOT NULL, record_hash TEXT NOT NULL, retained_fields_json TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY (spec_id, source_item_key)
);
CREATE TABLE collection_failures (
 failure_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES collection_runs,
 target TEXT NOT NULL, error_code TEXT NOT NULL, page_number INTEGER,
 snapshot_id TEXT REFERENCES source_snapshots, attempt_count INTEGER NOT NULL DEFAULT 1,
 state TEXT NOT NULL CHECK(state IN ('pending','resolved')), updated_at TEXT NOT NULL
);
CREATE TABLE collection_checkpoints (
 scope_key TEXT PRIMARY KEY, covered_from TEXT NOT NULL, checked_until TEXT NOT NULL,
 run_id TEXT NOT NULL REFERENCES collection_runs, updated_at TEXT NOT NULL
);
CREATE INDEX posts_author ON posts(author_id);
CREATE INDEX posts_published ON posts(published_at);
CREATE INDEX snapshots_run ON source_snapshots(run_id);
CREATE INDEX failures_pending ON collection_failures(state,run_id);
