from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import datetime
from database import insert_daily_record, insert_telemetry, init_db

app = FastAPI(title="Hardware Telemetry Receiver")

# Initialize DB on startup
init_db()

class TelemetryPayload(BaseModel):
    device_id: str
    cpu_temp: float
    fan_rpm: int = 0
    cpu_usage: float = 0.0
    is_spike: bool = False
    timestamp: Optional[str] = None

class DailyRecordPayload(BaseModel):
    device_id: str
    day: str
    reading_count: int
    average_temperature_c: float
    average_fan_rpm: float = 0.0
    average_cpu_usage: float = 0.0
    spike_count: int = 0
    updated_at: str

@app.post("/daily-record")
async def receive_daily_record(payload: DailyRecordPayload):
    insert_daily_record(payload.device_id, payload.model_dump())
    return {"status": "success", "message": "Daily record synchronized"}

@app.post("/telemetry")
async def receive_telemetry(payload: TelemetryPayload):
    try:
        timestamp = payload.timestamp or datetime.datetime.now().isoformat()
        insert_telemetry(
            device_id=payload.device_id,
            cpu_temp=payload.cpu_temp,
            fan_rpm=payload.fan_rpm,
            cpu_usage=payload.cpu_usage,
            is_spike=payload.is_spike,
            timestamp=timestamp
        )
        return {"status": "success", "message": "Telemetry saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/devices/{device_id}/metrics")
async def device_metrics(device_id: str):
    from database import get_device_metrics
    return get_device_metrics(device_id)

@app.get("/devices/{device_id}/rul")
async def device_rul(device_id: str):
    from database import get_device_metrics
    from rul_engine import compute_rul

    metrics = get_device_metrics(device_id)
    result = compute_rul(
        metrics["avg_temp"],
        metrics["total_spikes_over_85"],
        metrics["operating_hours"],
    )
    return {**metrics, "rul": result}

@app.get("/")
async def root():
    return {"message": "Hardware Diagnostics & Prognostics API is running"}
