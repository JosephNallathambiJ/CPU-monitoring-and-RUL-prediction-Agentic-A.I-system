"""Poll a monitoring agent on the target machine and store normalized telemetry."""

import argparse
import datetime
import json
import time
from typing import Any
from urllib.request import Request, urlopen

from database import init_db, insert_daily_record, insert_telemetry, update_sync_state


def _find_value(data: Any, names: set[str], default: Any = None) -> Any:
    if isinstance(data, dict):
        for name in names:
            if name in data and data[name] is not None:
                return data[name]
        for value in data.values():
            found = _find_value(value, names)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _find_value(value, names)
            if found is not None:
                return found
    return default


def normalize_status(status: dict[str, Any], device_id: str) -> dict[str, Any]:
    temperature = float(_find_value(
        status,
        {"cpu_temp", "temperature_c", "temperature_celsius", "hw_temperature_c"},
        0.0,
    ))
    fan_rpm = int(float(_find_value(status, {"fan_rpm", "current_rpm", "rpm"}, 0)))
    cpu_usage = float(_find_value(status, {"cpu_usage", "cpu_percent"}, 0.0))
    source_spike = _find_value(status, {"is_spike", "spike"}, False)
    if isinstance(source_spike, str):
        source_spike = source_spike.strip().lower() in {"1", "true", "yes", "on"}
    is_spike = bool(source_spike) or temperature >= 85.0
    source_timestamp = _find_value(status, {"timestamp"})
    if isinstance(source_timestamp, (int, float)):
        source_timestamp = datetime.datetime.fromtimestamp(
            source_timestamp, datetime.timezone.utc
        ).isoformat()

    return {
        "device_id": device_id,
        "cpu_temp": temperature,
        "fan_rpm": fan_rpm,
        "cpu_usage": cpu_usage,
        "is_spike": is_spike,
        "timestamp": source_timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def collect(monitor_url: str, device_id: str, interval: float) -> None:
    init_db()
    endpoint = monitor_url.rstrip("/") + "/api/status"
    print(f"Collecting {endpoint} for {device_id}; press Ctrl+C to stop")
    while True:
        try:
            request = Request(endpoint, headers={"Accept": "application/json"})
            with urlopen(request, timeout=min(max(interval, 2.0), 30.0)) as response:
                status = json.load(response)
            normalized = normalize_status(status, device_id)
            insert_telemetry(**normalized)
            print(normalized)
        except Exception as error:
            print(f"Monitoring source unavailable: {error}")
        time.sleep(interval)

def collect_daily_records(monitor_url: str, device_id: str, interval: float) -> None:
    """Synchronize compact records from the monitoring device over Wi-Fi."""
    init_db()
    endpoint = monitor_url.rstrip("/") + "/records"
    print(f"Synchronizing {endpoint} for {device_id}; press Ctrl+C to stop")
    while True:
        try:
            result = sync_daily_records(monitor_url, device_id, timeout=min(max(interval, 2.0), 30.0))
            print(
                f"Synchronized {result['daily_records']} daily records, "
                f"{result['spike_events']} spikes, {result['total_readings']} readings"
            )
        except Exception as error:
            print(f"Monitoring records unavailable: {error}")
        time.sleep(interval)


def sync_daily_records(monitor_url: str, device_id: str, timeout: float = 10.0) -> dict[str, Any]:
    """Fetch all compact records and upsert them into the prediction database."""
    init_db()
    endpoint = monitor_url.rstrip("/") + "/records"
    request = Request(endpoint, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    daily = payload.get("daily", [])
    spikes = payload.get("spikes", [])
    for record in daily:
        insert_daily_record(device_id, record)
    result = {
        "source": endpoint,
        "daily_records": len(daily),
        "spike_events": len(spikes),
        "total_readings": sum(int(record.get("reading_count", 0)) for record in daily),
        "monitoring_duration_hours": payload.get("monitoring_duration_hours", 0.0),
    }
    update_sync_state(device_id, result["monitoring_duration_hours"], result["daily_records"], result["total_readings"], result["spike_events"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect telemetry from a monitoring machine")
    parser.add_argument("--monitor-url", required=True, help="Target machine URL, e.g. http://192.168.1.20:8001")
    parser.add_argument("--device-id", required=True, help="Stable name for the monitored target")
    parser.add_argument("--interval", type=float, default=5.0, help="Telemetry polling interval in seconds")
    args = parser.parse_args()
    collect(args.monitor_url, args.device_id, args.interval)