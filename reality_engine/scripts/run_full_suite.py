"""Full-suite runner that writes a machine-readable verdict (shell pipes are unreliable here)."""
import io
import json
import sys
import time
import unittest
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "logs" / "suite_verdict.json"


def main() -> int:
    t0 = time.time()
    loader = unittest.TestLoader()
    suite = loader.discover("reality_engine/tests", pattern="test_*.py")
    buf = io.StringIO()
    runner = unittest.TextTestRunner(stream=buf, verbosity=0)
    result = runner.run(suite)
    verdict = {
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "was_successful": result.wasSuccessful(),
        "seconds": round(time.time() - t0, 1),
        "failed_tests": [str(t) for t, _ in list(result.failures) + list(result.errors)][:40],
        "tail": buf.getvalue()[-1500:],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(verdict, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in verdict.items() if k != "tail"}, indent=1))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
