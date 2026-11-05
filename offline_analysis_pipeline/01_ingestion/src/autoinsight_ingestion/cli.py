from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from .contracts import IngestionError, canonical
from .ingest import import_bytes, read_input, replay
from .storage import Repository


def main():
    parser = argparse.ArgumentParser(description="AutoInsight minimal ingestion service and maintenance")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ["import-legacy", "replay", "inspect", "verify", "export", "backup", "serve"]:
        p = sub.add_parser(command)
        p.add_argument("--data-root", required=True)
        if command == "import-legacy":
            p.add_argument("--input", required=True)
            p.add_argument("--member")
            p.add_argument("--kind", choices=["posts", "users", "series", "models", "parameters", "product_json"], required=True)
            p.add_argument("--series-id", default="")
            p.add_argument("--retrieved-at")
        if command == "replay":
            p.add_argument("--response-id", required=True)
        if command in {"export", "backup"}:
            p.add_argument("--output", required=True)
        if command == "export":
            p.add_argument("--format", choices=["jsonl", "csv"], default="jsonl")
        if command == "serve":
            p.add_argument("--sources")
            p.add_argument("--port", type=int, default=8876)
            p.add_argument("--allow-network", action="store_true")
            p.add_argument("--credential-file")
    for command in ['restore','migrate-v1']:
        p = sub.add_parser(command)
        p.add_argument("--input", required=True)
        p.add_argument("--data-root", required=True)
    args = parser.parse_args()
    try:
        if args.command == 'migrate-v1':
            from .migrate import migrate_v1
            result=migrate_v1(args.input,args.data_root)
        elif args.command == "restore":
            result = Repository.restore(args.input, args.data_root)
        else:
            with Repository(args.data_root) as store:
                if args.command == "import-legacy":
                    content, provenance = read_input(args.input, args.member)
                    result = import_bytes(store, content, args.kind, provenance, series_id=args.series_id, retrieved_at=args.retrieved_at)
                elif args.command == "replay":
                    result = replay(store, args.response_id)
                elif args.command in {"inspect", "verify"}:
                    result = store.verify()
                elif args.command == "export":
                    with Path(args.output).open("x", encoding="utf-8", newline="") as stream:
                        if args.format == "jsonl":
                            for row in store.logical_export():
                                stream.write(canonical(row) + "\n")
                        else:
                            fields = ["schema_version", "kind", "source_id", "raw_hash", "locator", "data_json"]
                            writer = csv.DictWriter(stream, fieldnames=fields)
                            writer.writeheader()
                            for row in store.logical_export():
                                writer.writerow({**{k: v for k, v in row.items() if k != "data"}, "data_json": canonical(row["data"])})
                    result = {"exported": True, "schema_version": "ingestion-2"}
                elif args.command == "backup":
                    result = store.backup(args.output)
                elif args.command == "serve":
                    from .api import make_server
                    from .jobs import JobService
                    sources = {}
                    if args.sources:
                        config_path = Path(args.sources).resolve()
                        sources = json.loads(config_path.read_text(encoding="utf-8"))
                        for source in sources.values():
                            source["path"] = str((config_path.parent / source["path"]).resolve())
                    service = JobService(store, sources, args.allow_network, credential_path=args.credential_file)
                    server = make_server(service, args.port, os.environ.get("INGESTION_API_TOKEN", ""))
                    print(canonical({"listening": "127.0.0.1", "port": server.server_port, "network_enabled": args.allow_network, "credentials": bool(args.credential_file)}), flush=True)
                    try:
                        server.serve_forever()
                    except KeyboardInterrupt:
                        pass
                    finally:
                        server.server_close()
                        service.close()
                    result = {"stopped": True}
        print(canonical(result))
        if args.command == "verify" and not result["ok"]:
            sys.exit(1)
    except IngestionError as error:
        print(canonical({"error_code": error.code}), file=sys.stderr)
        sys.exit(2)
    except (OSError, ValueError, KeyError):
        print(canonical({"error_code": "invalid_file_or_configuration"}), file=sys.stderr)
        sys.exit(2)
