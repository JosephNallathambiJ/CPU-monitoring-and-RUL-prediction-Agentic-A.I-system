import sqlite3
import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
DB_FILE = str(PROJECT_DIR / "telemetry.db")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            cpu_temp REAL,
            fan_rpm INTEGER,
            cpu_usage REAL,
            is_spike BOOLEAN,
            timestamp DATETIME
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_metrics (
            device_id TEXT NOT NULL,
            day TEXT NOT NULL,
            reading_count INTEGER NOT NULL,
            average_temperature_c REAL NOT NULL,
            average_fan_rpm REAL NOT NULL,
            average_cpu_usage REAL NOT NULL,
            spike_count INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (device_id, day)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sync_state (
            device_id TEXT PRIMARY KEY,
            monitoring_duration_hours REAL NOT NULL DEFAULT 0,
            daily_records INTEGER NOT NULL DEFAULT 0,
            total_readings INTEGER NOT NULL DEFAULT 0,
            spike_events INTEGER NOT NULL DEFAULT 0,
            synchronized_at TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def insert_daily_record(device_id: str, record: dict):
    conn = sqlite3.connect(DB_FILE)
    conn.execute('''
        INSERT INTO daily_metrics
        (device_id, day, reading_count, average_temperature_c, average_fan_rpm,
         average_cpu_usage, spike_count, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_id, day) DO UPDATE SET
          reading_count = excluded.reading_count,
          average_temperature_c = excluded.average_temperature_c,
          average_fan_rpm = excluded.average_fan_rpm,
          average_cpu_usage = excluded.average_cpu_usage,
          spike_count = excluded.spike_count,
          updated_at = excluded.updated_at
    ''', (
        device_id, record['day'], record.get('reading_count', 0),
        record.get('average_temperature_c', 0.0), record.get('average_fan_rpm', 0.0),
        record.get('average_cpu_usage', 0.0), record.get('spike_count', 0),
        record.get('updated_at', datetime.datetime.now(datetime.timezone.utc).isoformat()),
    ))
    conn.commit()
    conn.close()

def update_sync_state(device_id: str, duration_hours: float, daily_records: int, total_readings: int, spike_events: int):
        conn = sqlite3.connect(DB_FILE)
        conn.execute('''
            INSERT INTO sync_state
            (device_id, monitoring_duration_hours, daily_records, total_readings, spike_events, synchronized_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                monitoring_duration_hours = excluded.monitoring_duration_hours,
                daily_records = excluded.daily_records,
                total_readings = excluded.total_readings,
                spike_events = excluded.spike_events,
                synchronized_at = excluded.synchronized_at
        ''', (device_id, duration_hours, daily_records, total_readings, spike_events,
                datetime.datetime.now(datetime.timezone.utc).isoformat()))
        conn.commit()
        conn.close()

def insert_telemetry(device_id: str, cpu_temp: float, fan_rpm: int, cpu_usage: float, is_spike: bool, timestamp: str = None):
    if not timestamp:
        timestamp = datetime.datetime.now().isoformat()
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO telemetry (device_id, cpu_temp, fan_rpm, cpu_usage, is_spike, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (device_id, cpu_temp, fan_rpm, cpu_usage, is_spike, timestamp))
    conn.commit()
    conn.close()

def get_device_metrics(device_id: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT COALESCE(SUM(spike_count), 0),
               COALESCE(SUM(average_temperature_c * reading_count) / NULLIF(SUM(reading_count), 0), 0),
               COALESCE(SUM(reading_count), 0),
               COUNT(*)
        FROM daily_metrics WHERE device_id = ?
    ''', (device_id,))
    daily_spikes, daily_avg_temp, daily_readings, daily_days = cursor.fetchone()
    if daily_readings:
        cursor.execute('SELECT monitoring_duration_hours FROM sync_state WHERE device_id = ?', (device_id,))
        sync_row = cursor.fetchone()
        conn.close()
        return {
            "device_id": device_id,
            "avg_temp": daily_avg_temp,
            "total_spikes_over_85": daily_spikes,
            "operating_hours": sync_row[0] if sync_row else daily_days * 24.0,
            "daily_readings": daily_readings,
        }
    
    # Get total spikes
    cursor.execute('SELECT COUNT(*) FROM telemetry WHERE device_id = ? AND is_spike = 1', (device_id,))
    total_spikes = cursor.fetchone()[0]
    
    # Get average temp
    cursor.execute('SELECT AVG(cpu_temp) FROM telemetry WHERE device_id = ?', (device_id,))
    avg_temp_row = cursor.fetchone()
    avg_temp = avg_temp_row[0] if avg_temp_row[0] is not None else 0.0
    
    # Use source timestamps so polling frequency does not change the RUL rate.
    cursor.execute('''
        SELECT MIN(timestamp), MAX(timestamp), COUNT(*)
        FROM telemetry WHERE device_id = ?
    ''', (device_id,))
    first_timestamp, last_timestamp, total_records = cursor.fetchone()
    try:
        elapsed_seconds = (
            datetime.datetime.fromisoformat(last_timestamp).timestamp()
            - datetime.datetime.fromisoformat(first_timestamp).timestamp()
        )
        operating_hours = max(0.0, elapsed_seconds / 3600.0)
    except (TypeError, ValueError):
        # Preserve compatibility with legacy records that have no valid timestamp.
        operating_hours = total_records / 60.0
    
    conn.close()
    
    return {
        "device_id": device_id,
        "avg_temp": avg_temp,
        "total_spikes_over_85": total_spikes,
        "operating_hours": operating_hours
    }

def get_device_rul(device_id: str):
    """Return the latest aggregate metrics and RUL inputs for a device."""
    return get_device_metrics(device_id)

def get_device_spike_summary(device_id: str, hours: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    time_threshold = (datetime.datetime.now() - datetime.timedelta(hours=hours)).isoformat()
    
    cursor.execute('''
        SELECT COUNT(*), AVG(cpu_temp), SUM(is_spike), MAX(cpu_temp)
        FROM telemetry 
        WHERE device_id = ? AND timestamp >= ?
    ''', (device_id, time_threshold))
    
    row = cursor.fetchone()
    
    conn.close()
    
    return {
        "device_id": device_id,
        "hours": hours,
        "total_readings": row[0] or 0,
        "avg_cpu_temp": row[1] or 0.0,
        "total_spike_count": row[2] or 0,
        "max_temperature": row[3] or 0.0
    }

if __name__ == "__main__":
    init_db()
    print("Database initialized.")
