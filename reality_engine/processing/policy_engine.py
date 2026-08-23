"""Task 6: Policy ENI Severity(-5 to +5) * Probability(0-1) -> net_impact_score, agg >=0 pass"""

from dataclasses import dataclass

@dataclass
class PolicyRisk:
    policy_name: str
    severity: float  # -5 to +5
    probability: float  # 0-1
    time_horizon: str = "Mid-term"

    @property
    def eni(self) -> float:
        return round(self.severity * self.probability, 2)

def agg_policy_score(risks: list[PolicyRisk]) -> float:
    return round(sum(r.eni for r in risks), 2)

# Example: steel duty headwind -3.85 mock
if __name__ == "__main__":
    risks=[
        PolicyRisk("Steel Cust Duty Hike", -3.8, 0.85, "Short-term"),
        PolicyRisk("PLI Defence", 4.2, 0.7, "Structural"),
    ]
    print(f"ENI {risks[0].eni} agg {agg_policy_score(risks)} pass={agg_policy_score(risks)>=0}")
    # For HAL: PLI tailwind vs steel headwind → net +0.39
    # POLYPLEX: packaging policy headwind example
