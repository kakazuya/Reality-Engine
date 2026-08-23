"""Phase 2 Task 5: Moat rubric Moat=0.25*SC+0.25*NE+0.20*CA+0.20*IA+0.10*ES (0-5) → Wide >=3.5 Stable/Expanding"""

from dataclasses import dataclass

@dataclass
class MoatScores:
    switching_costs: int  # 0-5
    network_effects: int
    cost_advantage: int
    intangible_assets: int
    efficient_scale: int

    def total(self) -> float:
        return round(self.switching_costs*0.25 + self.network_effects*0.25 + self.cost_advantage*0.20 + self.intangible_assets*0.20 + self.efficient_scale*0.10, 2)

    def width(self) -> str:
        t=self.total()
        if t>=3.5: return "Wide"
        if t>=2.5: return "Narrow"
        return "None"

# Deterministic scorer from FTS/distilled params — LLM would emit this via Pydantic, scorer validates
def score_from_text(text: str) -> MoatScores:
    """Heuristic demo: keyword match → score (LLM extraction in prod via VisualArtifact.moat_impact)"""
    t=text.lower()
    sc=4 if any(k in t for k in ["switching cost","retention","sticky","lock-in"]) else 2 if "retention" in t else 1
    ne=4 if "network effect" in t or "platform" in t else 1
    ca=4 if "cost advantage" in t or "scale" in t else 2
    ia=4 if "brand" in t or "patent" in t or "intangible" in t else 2
    es=3 if "efficient scale" in t else 1
    return MoatScores(sc,ne,ca,ia,es)

# Example POLYPLEX 2.75 Narrow (from plan): SC4 NE1 CA3 IA3 ES2 → 2.75
if __name__ == "__main__":
    ex=MoatScores(4,1,3,3,2)
    print(f"POLYPLEX example {ex.total()} {ex.width()}")  # 2.75 Narrow
    for sym, scores in [("HAL",MoatScores(4,3,4,4,3)), ("TITAGARH",MoatScores(3,2,3,2,4))]:
        print(sym, scores.total(), scores.width())
