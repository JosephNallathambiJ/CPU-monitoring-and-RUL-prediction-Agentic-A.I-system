#!/usr/bin/env python3
"""Train the prediction-side RUL regression agent from telemetry history."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from rul_engine import compute_rul

FEATURES = ["avg_temp", "total_spikes", "operating_hours", "fan_rpm", "cpu_usage"]
PROJECT_DIR = Path(__file__).resolve().parent
ALIASES = {
    "avg_temp": ["avg_temp", "cpu_temp", "Temperature (°C)", "temperature_c"],
    "fan_rpm": ["fan_rpm", "current_rpm", "rpm"],
    "cpu_usage": ["cpu_usage", "CPU_Usage (%)", "cpu_percent"],
    "operating_hours": ["operating_hours", "Uptime (hrs)", "uptime_hours"],
    "total_spikes": ["total_spikes", "spikes", "spike_count"],
}


class RULRegressor:
    """Small dependency-light linear regressor for the prediction-side agent."""

    def __init__(self, feature_names: list[str]):
        self.feature_names = feature_names
        self.coefficients = np.zeros(len(feature_names) + 1)
        self.means = np.zeros(len(feature_names))
        self.scales = np.ones(len(feature_names))

    def fit(self, frame: pd.DataFrame, target: pd.Series) -> "RULRegressor":
        values = frame[self.feature_names].to_numpy(dtype=float)
        self.means = values.mean(axis=0)
        self.scales = np.where(values.std(axis=0) > 0, values.std(axis=0), 1.0)
        matrix = np.column_stack([np.ones(len(frame)), (values - self.means) / self.scales])
        self.coefficients = np.linalg.lstsq(matrix, target.to_numpy(), rcond=None)[0]
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        values = frame[self.feature_names].to_numpy(dtype=float)
        matrix = np.column_stack([np.ones(len(frame)), (values - self.means) / self.scales])
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            return matrix @ self.coefficients


if __name__ == "__main__":
    sys.modules.setdefault("train", sys.modules[__name__])
    RULRegressor.__module__ = "train"


def find_column(frame: pd.DataFrame, names: list[str]) -> str | None:
    normalized = {column.lower(): column for column in frame.columns}
    return next((normalized[name.lower()] for name in names if name.lower() in normalized), None)


def make_training_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    values = {}
    for feature in FEATURES:
        column = find_column(frame, ALIASES[feature])
        if column is not None:
            values[feature] = pd.to_numeric(frame[column], errors="coerce")
        else:
            values[feature] = 0.0

    prepared = pd.DataFrame(values).fillna(0.0)
    if find_column(frame, ALIASES["total_spikes"]) is None:
        prepared["total_spikes"] = (prepared["avg_temp"] >= 85.0).astype(float)

    target_column = find_column(frame, ["rul_hours", "RUL", "remaining_useful_life"])
    if target_column:
        target = pd.to_numeric(frame[target_column], errors="coerce")
    else:
        target = prepared.apply(
            lambda row: compute_rul(
                row["avg_temp"], int(row["total_spikes"]), row["operating_hours"]
            )["estimated_rul_hours"],
            axis=1,
        )

    valid = target.notna() & prepared.notna().all(axis=1)
    valid &= np.isfinite(target) & np.isfinite(prepared).all(axis=1)
    return prepared.loc[valid], target.loc[valid]


def main() -> int:
    parser = argparse.ArgumentParser(description="Train the IQAC prediction-side RUL model")
    parser.add_argument("--data", default=str(PROJECT_DIR.parent / "IoT_Failure_Prediction_Dataset.csv"))
    parser.add_argument("--model-output", default=str(PROJECT_DIR / "rul_model.joblib"))
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--random-state", type=int, default=42)
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        raise FileNotFoundError(f"Telemetry dataset not found: {data_path}")

    frame = pd.read_csv(data_path)
    features, target = make_training_frame(frame)
    if len(features) < 4:
        raise ValueError("At least four usable telemetry rows are required.")

    rng = np.random.default_rng(args.random_state)
    indices = rng.permutation(len(features))
    split_at = max(1, min(len(features) - 1, int(len(features) * (1 - args.test_size))))
    train_indices, test_indices = indices[:split_at], indices[split_at:]
    x_train, x_test = features.iloc[train_indices], features.iloc[test_indices]
    y_train, y_test = target.iloc[train_indices], target.iloc[test_indices]
    model = RULRegressor(FEATURES)
    model.fit(x_train, y_train)
    predictions = model.predict(x_test)
    errors = y_test.to_numpy() - predictions
    mae = float(np.mean(np.abs(errors)))
    denominator = float(np.sum((y_test.to_numpy() - y_test.mean()) ** 2))
    r2 = float(1.0 - np.sum(errors ** 2) / denominator) if denominator else 0.0

    output = Path(args.model_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": model,
            "features": FEATURES,
            "target": "estimated_rul_hours",
            "metrics": {
                "mae_hours": mae,
                "r2": r2,
            },
        },
        output,
    )
    print(f"Rows: {len(features)}")
    print(f"Validation MAE: {mae:.2f} hours")
    print(f"Validation R2: {r2:.4f}")
    print(f"Saved RUL model: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
