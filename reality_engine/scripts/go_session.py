"""Stable `x-opencode-session` ids for every OpenCode Go call (Shivam, 2026-10-20: standing rule for all routing calls).

OpenCode's Go docs: "Send a stable session ID in `x-opencode-session` for each conversation so we can optimize routing
and prompt caching." Until 2026-10-20 every call sent a fresh uuid4, which defeats the provider's prompt cache (our
prompts share a long fixed prefix: the instructions before {text}).

session_id(job, model, key, lane): a uuid5 of those parts, so the same job + model + key + lane gets the same id in every
run and every restart. lane defaults to the calling thread's pool index ("ThreadPoolExecutor-0_7" -> 7), so 32 parallel
workers use 32 stable sessions (sticky routing per worker, no single overloaded session). The key is only hashed into
the id, never sent or logged.
"""
import re
import threading
import uuid

NAMESPACE = uuid.UUID("6f3c1c52-6a3e-4d0e-9a2f-2026102000c0")


def lane():
    m = re.search(r"_(\d+)$", threading.current_thread().name)
    return int(m.group(1)) if m else 0


def session_id(job, model, key="", lane_no=None):
    model = str(model).split("~")[0]
    return str(uuid.uuid5(NAMESPACE, f"{job}|{model}|{uuid.uuid5(NAMESPACE, str(key))}|{lane() if lane_no is None else lane_no}"))
