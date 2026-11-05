"""Default offline test entry: permit loopback HTTP tests, reject external DNS/socket IO."""
import argparse
import json
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from autoinsight_ingestion.contracts import implementation_fingerprint


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--report")
    args = p.parse_args()
    original_connect = socket.socket.connect
    original_resolve = socket.getaddrinfo
    rejected = []

    def resolve(host, *rest, **kwargs):
        if host not in {"127.0.0.1", "localhost", "::1", None}:
            rejected.append("dns")
            raise AssertionError("external DNS forbidden during tests")
        return original_resolve(host, *rest, **kwargs)

    def connect(sock, address):
        if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
            rejected.append("socket")
            raise AssertionError("external socket forbidden during tests")
        return original_connect(sock, address)

    suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent))
    with patch.object(socket.socket, "connect", connect), patch.object(socket, "getaddrinfo", resolve):
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    if args.report:
        path = Path(args.report); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"implementation": implementation_fingerprint(), "tests": result.testsRun,
                                   "failures": len(result.failures), "errors": len(result.errors),
                                   "skipped": len(result.skipped), "external_network_guard": True,
                                   "rejected_external_attempts": len(rejected), "ok": result.wasSuccessful()},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
