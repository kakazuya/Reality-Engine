# Progress notes — HP capacity / accelerators (2026-10-31)

- Runner `reality_engine/scripts/hp_run.py` + `reality_engine/tests/test_hp_run.py` done: 10 passed.
  Survival measured: Start-Process dies with the ssh session; WMI (default) and schtasks/SYSTEM survive.
- QNN: no CUDA. Fixed input shapes put 100% of det/rec on QNN (no-fallback sessions + profile proof);
  no quantisation needed. 30 pages: CPU 15.1, NPU 159.7, GPU 86.1 pages/min; text agreement 0.971 / 0.611.
- Capacity: 8 simulated workers measured safe (commit left 8.56 GB, tasks <=1.45x). Real dsh ~208 MB
  resident. 6-8 recommended. Blocker found: `mcp` needs `cryptography`, no cp314 win_arm64 wheel.
- dsh: Bun 1.4.4 native but dsh cannot boot under Bun (V8 symbols); Node 24.22.2 ARM64 runs it; real
  Go call OK in 9.2 s, stable session id. Tokens not exposed by --json.
- Network: 8.92 MiB/s Tailscale, 10.00 MiB/s LAN, 11.51 MiB/s with 3 streams; raw TCP blocked by firewall.
- Raw copy completed (19,978 files). Report written to tasks/efficiency/HP_ACCEL_BENCH_2026-10-31.md.
- Next: nothing blocking; open items are in the report §7 (Python 3.13 for MCP, node shim for dsh, git).
