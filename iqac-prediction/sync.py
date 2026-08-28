#!/usr/bin/env python3
"""Synchronize recorded monitoring history into the prediction database."""

from __future__ import annotations

import argparse
import json

from monitor_client import sync_daily_records


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize monitoring records over Wi-Fi")
    parser.add_argument("--monitor-url", required=True, help="Monitoring device URL, e.g. http://192.168.1.20:8001")
    parser.add_argument("--device-id", required=True, help="Stable ID for the monitored device")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    try:
        result = sync_daily_records(args.monitor_url, args.device_id, args.timeout)
    except Exception as error:
        parser.exit(1, f"Synchronization failed: {error}\n")
    print(json.dumps({"status": "synchronized", **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())