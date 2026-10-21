# Codex heartbeat integration follow-up

Follow your original heartbeat task and restart security note. Only edit your original allowed heartbeat/launcher/test/report paths. A separate plugin worker owns `plugins/dsh-worker/**`; do not edit those. No model calls from tests, no security bypasses, no unrelated edits.

The local MCP plugin needs to send authenticated steering to this SAME launcher-controlled agent. Currently the wrapper unconditionally generates an in-memory token/run ID, so the plugin supervisor cannot reuse its own per-job credential or call the adapter after an MCP restart. Add a supported minimal integration seam: accept a valid inherited `DSH_HEARTBEAT_TOKEN` (at least 32 chars, bounded) and optional inherited `DSH_HEARTBEAT_RUN_ID` from the invoking supervisor, generating fresh values when omitted. Keep credentials out of argv, status files and normal logs. The supervisor can persist its own per-job token privately in gitignored runtime; wrapper must not expose it. Document this contract precisely, including control-file path, header, JSON body, response ACK semantics and current nested status schema. Prefer using the existing control endpoint, not adding another helper process.

Check the shipped Node adapter supports ordinary follow-up messages as well as automatic status nudges. Preserve complete requested text within the documented input bound (do not silently truncate at 4000 chars when caller accepts 32 KiB); reject oversize requests explicitly. Label manual follow-ups accurately while preserving genuine steer delivery to the same running agent. Wrong run/session IDs and queued ACK alone must never count as a response. Add actual adapter tests (offline) for these cases and inherited credentials. Let plugin worker implement its side separately.

Review real integration-test cleanup on failures: kill owned whole dsh process tree, wait/reap process and drain pipes safely. A bare process.kill() on Windows dsh.exe may leave its Node child/listener. Test the actual shipped dsh plugin against the in-process fake HTTP model and preserve useful failure diagnostics.

Do not claim streaming token-level activity if this dsh build emits only committed messages; document the observability limit. The requested 15m ping / 15m second ping / 15m final response window should remain exact, with no default hard runtime cap.

Implement and run combined heartbeat + existing controls tests. Return actual changes/tests and any remaining limits for Codex review.
