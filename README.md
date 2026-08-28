# IQAC Monitoring and AI Agents

IQAC is a Python monitoring and predictive-maintenance project for computers, IoT edge devices, drones, and other monitored hardware. It combines operating-system telemetry, several specialized decision agents, threshold alerts, machine-learning inference, compact SQLite recording, and a separate Remaining Useful Life (RUL) prediction service.

## What the project does

The project has four complementary capabilities:

1. **Live monitoring:** reads CPU, memory, battery, disk, and available temperature sensors through `psutil`.
2. **Agent decisions:** runs thermal, fan, voltage, and CPU-performance agents. Each agent has its own configuration, sensors, actuators, learning code, and optional web interface.
3. **Failure prediction:** trains XGBoost classifiers from IoT telemetry and loads saved `.joblib` artifacts during agent inference.
4. **Predictive maintenance:** records daily telemetry and spike events on the monitored device, then synchronizes those summaries to a separate machine that calculates RUL.

The default design is intentionally tolerant of missing hardware. When a platform does not expose battery or temperature sensors, the monitor continues with the values that are available.

## Repository structure

| Path | Purpose |
| --- | --- |
| `run.py` | Production entry point. Starts the monitoring loop and records API together. |
| `simulation.py` | Cross-platform agent smoke test and continuous monitoring loop. |
| `hardware_monitor.py` | Raspberry Pi/Linux DS18B20 monitor using Agent 1 and the records API. |
| `spike.py` | Lightweight CPU, memory, temperature, and battery threshold monitor. |
| `recorder.py` | FastAPI `/records` service and SQLite daily-metric recorder. |
| `data_learn.py` | Trains one IoT failure classifier. |
| `train_all_agents_ml.py` | Trains the IoT and commercial thermal models, then copies artifacts to agents. |
| `agent_ml_runtime.py` | Converts live agent state into model features and performs inference. |
| `agent1/` | Model-based, utility-based thermal monitoring and learning agent. |
| `agent2/` | PID fan-speed and active-cooling agent. |
| `agent3/` | Multi-rail voltage and electrical-power protection agent. |
| `agent4/` | CPU frequency and performance-management agent. |
| `agent5/` | Supervisor and process-health components. |
| `iqac-prediction/` | Separate telemetry synchronization, database, RUL engine, and API. |
| `agent_ml_models/` | Shared trained model artifacts. |
| `commercial_thermal_map_dataset-main/` | Commercial thermal benchmark data used by the all-agent trainer. |

## Architecture and data flow

```text
OS sensors / hardware callbacks
						|
						v
		 agent1 ... agent4  ---->  optional ML prediction
						|
						+----> console summaries and threshold alerts
						|
						+----> recorder.py -> monitoring_records.db -> GET /records
																										 |
																										 v
																			iqac-prediction/sync.py
																										 |
																										 v
																			prediction SQLite DB -> RUL API
```

`simulation.py` creates a fresh system snapshot for each cycle and executes one step for each selected agent. `run.py` uses the same loop with recording enabled. The recorder does not store every raw reading forever: it aggregates daily count, temperature minimum/maximum/average, CPU average, fan-RPM average, and individual spike events.

## Installation

Create the root environment and install the runtime dependencies:

```bash
cd /Users/dsceimaclab03/Downloads/iqac
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The root requirements are sufficient for monitoring and recording. The training scripts also import the scientific ML stack, so install these before training if they are not already present:

```bash
python -m pip install scikit-learn imbalanced-learn xgboost
```

The separate prediction service has its own environment and requirements file:

```bash
cd iqac-prediction
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Each agent also contains a local `requirements.txt` for running that agent independently. The root scripts are the recommended way to run the complete system.

## Run the lightweight spike monitor

This command checks the current machine without starting any agent or database service:

```bash
source .venv/bin/activate
python spike.py --interval 2 --cpu-threshold 80 --memory-threshold 85 --temp-threshold 70
```

It prints one snapshot per interval and reports a spike when CPU, memory, or temperature is above its limit, or when battery is below its low-battery limit. Use `--steps 5` for a finite five-check run. Stop continuous monitoring with Ctrl+C.

## Run the agent simulation

Run all four runtime agents continuously:

```bash
source .venv/bin/activate
python simulation.py
```

Useful finite and selective runs:

```bash
python simulation.py --agents agent1 agent2 --steps 3 --interval 1
python simulation.py --agents agent3 --steps 1
```

The output includes each agent's current measurement and action summary. Agent results are isolated: an error in one agent is printed as an error while the loop can continue with the others.

## Run production monitoring with recording

`run.py` starts both the monitoring loop and a FastAPI records server:

```bash
source .venv/bin/activate
python run.py --agents agent1 agent2 agent3 agent4 --interval 5 --port 8001
```

Options include:

- `--agents`: one or more agent names; defaults to `agent1 agent2 agent3 agent4`.
- `--interval`: seconds between cycles; must be greater than zero.
- `--host`: API bind address; defaults to `0.0.0.0` for a network deployment.
- `--port`: records API port; defaults to `8001`.

The records service exposes:

- `GET /` — health response.
- `GET /records` — all daily summaries, spike events, and monitoring duration.
- `GET /records?since=2026-01-01` — summaries from the specified day onward.

The database is created as `monitoring_records.db` beside `recorder.py`. It is local to the monitored device and is safe to leave out of source control.

## Agents

- **Agent 1:** maintains a thermal belief state, estimates temperature trends, evaluates utility across safety, performance, and power, and learns baselines in `temperature_history.db`.
- **Agent 2:** uses a PID controller and cooling model to select fan RPM/PWM while considering temperature, power, noise, and fan health. Its history is stored in `rpm_cooling_history.db`.
- **Agent 3:** monitors VCore, 12 V, 5 V, 3.3 V, and battery rails, detects sag/surge/brownout conditions, and stores voltage history in `voltage_history.db`.
- **Agent 4:** monitors CPU frequency and load and selects performance governor behavior using its configured profile.
- **Agent 5:** contains supervisory and process-health components used by the broader project; it is not part of the default four-agent simulation loop.

Each agent supports configurable profiles such as `laptop`, `computer`, `drone`, and `iot`. The agent-specific README files describe standalone CLI tests, web dashboards, and hardware callback registration.

## Train and distribute models

### Train one IoT model

`data_learn.py` detects `IoT_Failure_Prediction_Dataset.csv` automatically when no data path is supplied. The default target is `Failure_Type`; common aliases such as `failure_flag` are resolved when present.

```bash
source .venv/bin/activate
python data_learn.py \
	--data IoT_Failure_Prediction_Dataset.csv \
	--target Failure_Type \
	--model-output iot_failure_model.joblib \
	--explain-n 5
```

The trainer separates numeric and categorical columns, imputes missing values, scales numeric values, one-hot encodes categorical values, applies SMOTE to the training split, trains XGBoost, reports macro-F1/classification metrics, and saves a joblib bundle containing the model, preprocessor, feature names, and metrics. Pass `--no-llm` or `--explain-n 0` to skip optional Ollama explanations.

### Train all agent artifacts

This command trains the IoT model, builds a three-level commercial thermal-risk model from the pickle files, saves both to `agent_ml_models/`, and copies the IoT model to each agent directory:

```bash
python train_all_agents_ml.py
```

Override the input and output locations when necessary:

```bash
python train_all_agents_ml.py \
	--iot-data IoT_Failure_Prediction_Dataset.csv \
	--thermal-dir commercial_thermal_map_dataset-main/data_files \
	--output-dir agent_ml_models \
	--explain-n 0
```

If an agent model cannot be loaded, `AgentMLRuntime` returns a no-model result and the monitoring/control loop remains usable. This makes model artifacts optional at runtime, although trained artifacts are recommended for predictive behavior.

## Separate RUL prediction system

The RUL system is designed for two machines. The monitored device exposes its records API; the prediction machine pulls those records and keeps its own database. No shared directory or shared database is required.

On the monitored device, start production monitoring and note its LAN address, for example `192.168.1.20:8001`. On the prediction machine, synchronize records continuously:

```bash
cd /Users/dsceimaclab03/Downloads/iqac/iqac-prediction
source .venv/bin/activate
python main.py --collect-url http://192.168.1.20:8001 --device-id target-cpu --interval 5
```

Start the prediction API in another terminal:

```bash
python main.py --serve --port 8000
```

The API runs on `http://127.0.0.1:8000`. RUL and diagnostic routes are implemented by `iqac-prediction/api.py`; the device-specific RUL route is:

```text
GET /devices/target-cpu/rul
```

To perform one manual synchronization instead of polling continuously:

```bash
python sync.py --monitor-url http://192.168.1.20:8001 --device-id target-cpu
```

The command reports synchronized daily records, spike events, and readings. Repeating it updates existing days rather than duplicating them.

## Hardware integration

For a first physical IoT deployment, connect a DS18B20 temperature sensor to a Raspberry Pi or Linux gateway and run:

```bash
source .venv/bin/activate
python hardware_monitor.py --interval 5 --host 0.0.0.0 --port 8001
```

This discovers `/sys/bus/w1/devices/28-*/w1_slave`, verifies the sensor CRC, registers the reading with Agent 1, records daily metrics and spikes, and exposes `/records` for the separate prediction computer. Use `--sensor-id 28-...` when multiple DS18B20 sensors are connected. Wiring and complete two-device instructions are in [guide.txt](guide.txt).

The agents also provide callback hooks for physical sensors and actuators. Agent 1 can accept temperature callbacks, Agent 2 can accept fan-RPM and PWM callbacks, and Agent 3 can accept voltage ADC and power-actuator callbacks. Add these one at a time after the temperature workflow is working. See the agent-specific READMEs for examples using I2C, GPIO, Linux hwmon, Arduino, and relay/VRM integrations.

## Troubleshooting

- **Temperature is `None`:** many macOS systems do not expose temperature sensors through `psutil`; use a physical callback or continue with CPU/memory telemetry.
- **Battery is `None`:** desktop systems and some virtual machines have no battery interface.
- **An ML model is skipped:** verify the `.joblib` path and install compatible ML dependencies; monitoring still runs without it.
- **The prediction machine cannot connect:** confirm the monitored device binds to `0.0.0.0`, the port is reachable on the local network, and the URL does not point to `127.0.0.1` on the wrong machine.
- **A port is busy:** choose another value with `run.py --port ...` or `main.py --serve --port ...`.

## Stopping and generated files

Press Ctrl+C to stop a continuous monitor, collector, or simulation. Runtime databases and telemetry files may include:

- `monitoring_records.db`
- `iqac-prediction/*.db`
- `iqac-prediction/shared_telemetry.json`
- agent-specific history databases

These are generated state, not source code. Back them up when historical monitoring data matters and avoid committing them to version control.
