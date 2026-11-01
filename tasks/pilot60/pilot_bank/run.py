"""Entry point: load every rule file, then build the bank."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build  # noqa: E402
import rules_a, rules_b, rules_c, rules_d, rules_e, rules_f  # noqa: E402,F401,E401

build.main()
