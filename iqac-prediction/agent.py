from database import get_device_metrics
from rul_engine import compute_rul
from typing import Any

def tool_get_spike_metrics(device_id: str) -> str:
    """Fetches device telemetry metrics including avg_temp, spikes, and operating_hours."""
    metrics = get_device_metrics(device_id)
    return str(metrics)

def tool_compute_rul(params_str: str) -> str:
    """
    Computes RUL. Input must be a comma-separated string: avg_temp, total_spikes, operating_hours.
    Example input: "65.5, 12, 120.5"
    """
    try:
        parts = [p.strip() for p in params_str.split(',')]
        avg_temp = float(parts[0])
        spikes = int(parts[1])
        hours = float(parts[2])
        result = compute_rul(avg_temp, spikes, hours)
        return str(result)
    except Exception as e:
        return f"Error computing RUL: {str(e)}. Make sure input is 'avg_temp, total_spikes, operating_hours'"

def run_formula_rul_agent(metrics: dict[str, Any], formula: dict[str, Any]) -> dict[str, Any]:
    """Run the prediction agent's deterministic formula workflow on shared telemetry."""
    expression = formula["remaining_useful_life_formulas"]["degradation_forecasting"]["linear_degradation"]["rul_expression"]
    rul = compute_rul(
        float(metrics["avg_temp"]),
        int(metrics["total_spikes"]),
        float(metrics["operating_hours"]),
    )
    return {
        "agent": "iqac-rul-prediction-agent",
        "input": metrics,
        "formula_expression": expression,
        "rul": rul,
    }

def run_diagnostic_agent(device_id: str):
    from langchain.agents import initialize_agent, AgentType, Tool
    from langchain_community.llms import Ollama

    # Initialize the LLM
    llm = Ollama(model="qwen2.5:7b", temperature=0.2)
    
    # Define Tools
    tools = [
        Tool(
            name="get_spike_metrics",
            func=tool_get_spike_metrics,
            description="Fetches device telemetry metrics. Input should be the device_id as a string."
        ),
        Tool(
            name="compute_rul",
            func=tool_compute_rul,
            description="Computes RUL. Input MUST be a comma-separated string: avg_temp, total_spikes, operating_hours."
        )
    ]
    
    prompt = """You are a specialized Hardware Diagnostics & Prognostics AI Agent.
Your objective is to diagnose CPU health and predict Remaining Useful Life (RUL) based on telemetry.
You MUST follow this exact strict structured reasoning:
Step 1: Fetch target device metrics using get_spike_metrics.
Step 2: Run the RUL math tool using compute_rul based on the metrics fetched in Step 1.
Step 3: Output a final diagnostic report covering root-cause diagnosis (e.g., thermal paste degradation, fan failure, dust accumulation) and actionable mitigation steps.

Device ID to analyze: {input}

{agent_scratchpad}
"""
    
    agent = initialize_agent(
        tools, 
        llm, 
        agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=True,
        max_iterations=5,
        handle_parsing_errors=True
    )
    
    # Run the agent
    print(f"Starting diagnosis for {device_id}...\n")
    try:
        # Pass the formatted prompt implicitly by appending instructions to the input
        # Note: Langchain zero shot react has its own prompt, we are overriding the input to enforce behavior.
        response = agent.run(
            f"Follow the strict 3-step reasoning to diagnose Device ID: {device_id}. \n"
            "Step 1: Fetch metrics with 'get_spike_metrics'. \n"
            "Step 2: Compute RUL with 'compute_rul' using the fetched data (format: avg_temp, spikes, hours). \n"
            "Step 3: Output a detailed diagnostic report explaining root causes and mitigation steps."
        )
        return response
    except Exception as e:
        return f"Agent encountered an error: {e}"

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        dev_id = sys.argv[1]
    else:
        dev_id = "device_001"
    report = run_diagnostic_agent(dev_id)
    print("\n--- Final Diagnostic Report ---")
    print(report)
