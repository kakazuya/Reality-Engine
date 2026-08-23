"""Task 7: Financial secondary validation ROIC>WACC spread>0.05 only after moat/policy"""

def is_financially_valid(roic: float, wacc: float, fcf_margin: float = None) -> bool:
    spread = roic - wacc
    return spread > 0.05

if __name__ == "__main__":
    tests=[(0.18,0.10,True),(0.06,0.05,False),(0.12,0.08,False)]
    for roic,wacc,exp in tests:
        print(roic, wacc, is_financially_valid(roic,wacc), "expect", exp)
