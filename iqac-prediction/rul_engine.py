import math

def compute_rul(avg_temp: float, total_spikes_over_85: int, operating_hours: float) -> dict:
    """
    Computes Remaining Useful Life (RUL) using a simplified Arrhenius equation 
    and a cumulative thermal stress model.
    """
    # Constants for simplified Arrhenius model
    BASE_LIFE_HOURS = 50000.0  # Assumed life at reference temp
    REF_TEMP_C = 40.0
    ACTIVATION_ENERGY = 0.5  # eV
    BOLTZMANN_CONST = 8.617333262145e-5  # eV/K
    
    # Convert temps to Kelvin
    t_ref_k = REF_TEMP_C + 273.15
    t_avg_k = avg_temp + 273.15
    
    if avg_temp <= 0:
        return {
            "health_score_pct": 100.0,
            "estimated_rul_hours": BASE_LIFE_HOURS,
            "risk_level": "Low"
        }
    
    # Acceleration Factor (AF)
    # AF = exp( (Ea / k) * (1/T_ref - 1/T_use) )
    try:
        af = math.exp((ACTIVATION_ENERGY / BOLTZMANN_CONST) * ((1.0 / t_ref_k) - (1.0 / t_avg_k)))
    except OverflowError:
        af = 100.0 # Cap if temperature is absurdly high
        
    # Adjust expected life based on average temp
    expected_life_hours = BASE_LIFE_HOURS / af if af > 0 else BASE_LIFE_HOURS
    
    # Apply penalty for thermal spikes (>85C)
    # Assume each spike takes 5 hours off the life as thermal stress damage
    spike_penalty = total_spikes_over_85 * 5.0
    
    remaining_life = expected_life_hours - operating_hours - spike_penalty
    remaining_life = max(0.0, remaining_life)
    
    health_score_pct = (remaining_life / BASE_LIFE_HOURS) * 100.0
    health_score_pct = max(0.0, min(100.0, health_score_pct))
    
    if health_score_pct > 70:
        risk_level = "Low"
    elif health_score_pct > 30:
        risk_level = "Moderate"
    else:
        risk_level = "Critical"
        
    return {
        "health_score_pct": round(health_score_pct, 2),
        "estimated_rul_hours": round(remaining_life, 2),
        "risk_level": risk_level
    }
