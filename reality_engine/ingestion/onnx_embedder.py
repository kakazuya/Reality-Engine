"""Local ONNX embedding backend on DirectML (RX 6700 XT) with CPU fallback.

Model: Xenova/bge-small-en-v1.5 (BAAI/bge-small-en-v1.5 port, 384-dim,
mean pooling, L2-normalized — same contract as the hash fallback it
replaces, so no schema or consumer migration).
Files (from the HuggingFace repo, ``onnx/`` subfolder + ``tokenizer.json``):

- https://huggingface.co/Xenova/bge-small-en-v1.5/resolve/main/onnx/model.onnx
- https://huggingface.co/Xenova/bge-small-en-v1.5/blob/main/onnx/model_quantized.onnx
- https://huggingface.co/Xenova/bge-small-en-v1.5/resolve/main/tokenizer.json

Usage contract (per the model card — feature-extraction, mean pooling,
normalize=True) + DirectML execution provider (per the ORT DirectML doc —
providers=[DmlExecutionProvider, CPUExecutionProvider], sequential mode;
DML sessions are NOT thread-safe for concurrent Run, so batching happens
outside the session under a lock).

Sources:
- https://huggingface.co/Xenova/bge-small-en-v1.5 (usage: pipeline
  'feature-extraction', {pooling:'mean', normalize:true}, dims [N, 384])
- https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html
  (DML EP setup; "does not support multi-threaded calls to Run on the same
  inference session" — one thread per session; batch outside the session)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("reality_engine.onnx_embedder")

MODEL_ID = "Xenova/bge-small-en-v1.5"
DIMENSION = 384
MAX_TOKENS = 512  # bge-small-en-v1.5 context window

# Retrieval instruction the bge family was trained with (bge-small-en-v1.5
# README / BAAI usage: queries carry the instruction, passages do not).
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def default_model_dir() -> Path:
    from reality_engine import config

    return Path(config.DATA_DIR) / "models" / "bge-small-en-v1.5"


class OnnxEmbedder:
    """Batched ONNX feature-extraction on DirectML, CPU fallback.

    Lazy: nothing downloads and no session is created until the first
    ``embed`` call. ``available`` is False (and every call falls back to
    ``None``) when deps/files are missing — callers keep their hash
    fallback. Thread-safe via an internal lock (DML Run is sequential).
    """

    def __init__(
        self,
        model_dir: Optional[Path] = None,
        prefer_gpu: bool = True,
        batch_size: int = 64,
        gpu_duty: Optional[float] = None,
        backend: Optional[str] = None,
    ) -> None:
        self.model_dir = Path(model_dir) if model_dir else default_model_dir()
        self.prefer_gpu = prefer_gpu
        self.batch_size = max(1, int(batch_size))
        # --- inference backend -------------------------------------------------
        # "auto"   : Vulkan when a server is reachable, else ONNX. DEFAULT —
        #            measured ~2x faster (see below) with ONNX fallback on any
        #            failure, so library/test use still works server-down.
        # "onnx"   : in-process ONNX Runtime (DirectML on this box) only.
        #            Set REALITY_ENGINE_EMBED_BACKEND=onnx to force it.
        # "vulkan" : llama.cpp embedding server (Vulkan) over HTTP.
        #
        # Measured on this machine, identical inputs and matched mean pooling:
        #   Vulkan 65.4 chunks/s vs DirectML 31.8 chunks/s (2.06x), vector
        #   agreement cosine 0.99987 with 98% top-5 retrieval overlap. The Vulkan
        #   stack is also the one that does not die with a native access
        #   violation every ~6 minutes — hence auto is the default.
        self.backend = (backend or os.environ.get("REALITY_ENGINE_EMBED_BACKEND", "auto")).strip().lower()
        self.embed_server = os.environ.get("REALITY_ENGINE_EMBED_SERVER", "http://127.0.0.1:8099").rstrip("/")
        self.vulkan_batch = int(os.environ.get("REALITY_ENGINE_VULKAN_BATCH", "32") or 32)
        self._vulkan_state: Optional[bool] = None      # None = unknown, False = disabled
        self._tok_only = None                           # tokenizer for server-side fitting
        if gpu_duty is None:
            try:
                gpu_duty = float(os.environ.get("REALITY_ENGINE_GPU_DUTY", "0.90"))
            except ValueError:
                gpu_duty = 0.90
        # Keep a hard headroom ceiling even when an old launcher exports 1.0.
        self.gpu_duty = min(0.96, max(0.05, float(gpu_duty)))
        self._lock = threading.Lock()
        self._session = None
        self._tokenizer = None
        self._provider: Optional[str] = None
        self._probed = False
        self._available: Optional[bool] = None
        self._resource_guard = None

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------
    @property
    def provider(self) -> Optional[str]:
        """'DML' | 'CPU' | None (None = unavailable). Triggers lazy init."""
        self._ensure()
        return self._provider

    @property
    def available(self) -> bool:
        self._ensure()
        return bool(self._available)

    def _model_files(self) -> Optional[tuple]:
        for name in ("model.onnx", "model_quantized.onnx"):
            onnx = self.model_dir / "onnx" / name
            tok = self.model_dir / "tokenizer.json"
            if onnx.exists() and tok.exists():
                return onnx, tok
        return None

    def _ensure(self) -> bool:
        if self._probed:
            return bool(self._available)
        self._probed = True
        try:
            import onnxruntime as ort  # type: ignore
        except ImportError:
            logger.info("onnx_embedder: onnxruntime missing — embeddings stay hash fallback")
            self._available = False
            return False
        try:
            from tokenizers import Tokenizer  # type: ignore
        except ImportError:
            logger.info("onnx_embedder: tokenizers missing — embeddings stay hash fallback")
            self._available = False
            return False
        files = self._model_files()
        if files is None:
            logger.info("onnx_embedder: no model in %s — run `cli.py embed-setup`", self.model_dir)
            self._available = False
            return False
        onnx_path, tok_path = files
        try:
            providers = ort.get_available_providers()
            use_dml = self.prefer_gpu and "DmlExecutionProvider" in providers
            opts = ort.SessionOptions()
            # DML EP requires sequential execution mode (per ORT DirectML doc).
            opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            sess_providers = (
                ["DmlExecutionProvider", "CPUExecutionProvider"]
                if use_dml
                else ["CPUExecutionProvider"]
            )
            self._session = ort.InferenceSession(
                str(onnx_path), sess_options=opts, providers=sess_providers
            )
            self._provider = "DML" if use_dml else "CPU"
            self._tokenizer = Tokenizer.from_file(str(tok_path))
            self._available = True
            logger.info("onnx_embedder: session ready (%s, %s)", self._provider, onnx_path.name)
        except Exception as exc:
            logger.warning("onnx_embedder: session init miss: %s", exc)
            self._available = False
        return bool(self._available)

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------
    def ensure_downloaded(self) -> bool:
        """Fetch onnx/model.onnx + tokenizer.json via huggingface_hub. True on success."""
        try:
            from huggingface_hub import hf_hub_download  # type: ignore
        except ImportError:
            logger.warning("onnx_embedder: huggingface_hub missing — pip install huggingface_hub")
            return False
        try:
            self.model_dir.mkdir(parents=True, exist_ok=True)
            for remote, local in (
                ("onnx/model.onnx", self.model_dir / "onnx" / "model.onnx"),
                ("tokenizer.json", self.model_dir / "tokenizer.json"),
            ):
                if local.exists():
                    continue
                local.parent.mkdir(parents=True, exist_ok=True)
                got = hf_hub_download(repo_id=MODEL_ID, filename=remote, local_dir=self.model_dir)
                # hf_hub_download mirrors the repo layout (local_dir/onnx/...);
                # move into place when it lands elsewhere.
                if Path(got) != local and Path(got).exists():
                    Path(got).replace(local)
            ok = self._model_files() is not None
            if ok:
                self._probed = False  # re-probe now that files exist
            return ok
        except Exception as exc:
            logger.warning("onnx_embedder: download miss: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------
    def _encode_batch(self, texts: List[str], is_query: List[bool]) -> List[List[float]]:
        import numpy as np  # type: ignore

        enc = self._tokenizer.encode_batch(
            [(QUERY_PREFIX + t if q else t) for t, q in zip(texts, is_query)]
        )
        ids = np.array(
            [e.ids[:MAX_TOKENS] + [0] * max(0, MAX_TOKENS - len(e.ids)) for e in enc],
            dtype=np.int64,
        )
        mask = np.array(
            [
                [1] * min(len(e.ids), MAX_TOKENS) + [0] * max(0, MAX_TOKENS - len(e.ids))
                for e in enc
            ],
            dtype=np.int64,  # graph expects int64 for all three inputs (probed live)
        )
        names = [i.name for i in self._session.get_inputs()]
        feeds = {"input_ids": ids, "attention_mask": mask,
                 "token_type_ids": __import__("numpy").zeros_like(ids, dtype=__import__("numpy").int64)}
        inputs = {n: feeds[n] for n in names if n in feeds}
        # Mean pooling over non-padding tokens, then L2 normalize
        # (model card: {pooling:'mean', normalize:true}).
        out_names = [o.name for o in self._session.get_outputs()]
        (last_hidden,) = self._session.run(out_names[:1], inputs)
        mask3 = mask[:, :, None]
        summed = (last_hidden * mask3).sum(axis=1)
        counts = mask3.sum(axis=1).clip(min=1e-9)
        emb = summed / counts
        norms = np.linalg.norm(emb, axis=1, keepdims=True).clip(min=1e-12)
        return (emb / norms).astype(np.float32).tolist()

    def embed_many(self, texts: List[str], is_query: bool = False) -> Optional[List[List[float]]]:
        """Batched embed; None when the backend is unavailable (caller falls back)."""
        if not texts:
            return []
        if self.backend in ("vulkan", "auto") and self._vulkan_ready():
            out = self._vulkan_embed_many(texts, is_query=is_query)
            if out is not None:
                return out
            if self.backend == "vulkan":
                # Vulkan-only: never silently fall back to DirectML/CPU here.
                # Missing vectors surface as NULL embeddings, not wrong-model vectors.
                logger.error("onnx_embedder: vulkan-only backend and server batch failed; returning None")
                return None
            # fall through to ONNX on any server failure
        if self.backend == "vulkan":
            logger.error("onnx_embedder: vulkan-only backend and server unreachable; returning None")
            return None
        if not self._ensure():
            return None
        out: List[List[float]] = []
        flags = [is_query] * len(texts)
        with self._lock:  # DML Run is sequential per session (ORT DirectML doc)
            for i in range(0, len(texts), self.batch_size):
                started = time.perf_counter()
                try:
                    out.extend(self._encode_batch(texts[i : i + self.batch_size], flags[i : i + self.batch_size]))
                except Exception as exc:
                    logger.warning("onnx_embedder: batch miss (%d texts): %s", len(texts), exc)
                    return None
                self._duty_sleep(time.perf_counter() - started)
        return out

    # ------------------------------------------------------------------
    # Vulkan backend (llama.cpp embedding server)
    # ------------------------------------------------------------------
    def _vulkan_ready(self) -> bool:
        """Probe the embedding server once; cache the verdict for the process."""
        if self._vulkan_state is not None:
            return self._vulkan_state
        if self.backend == "vulkan" and not self.embed_server:
            self._vulkan_state = False
            return False
        try:
            import requests  # local import: only needed for this backend
            r = requests.get(f"{self.embed_server}/health", timeout=3)
            self._vulkan_state = bool(r.status_code == 200 and "ok" in r.text.lower())
            if self._vulkan_state:
                logger.info("onnx_embedder: backend=vulkan (%s)", self.embed_server)
            else:
                logger.warning("onnx_embedder: vulkan server unhealthy, using ONNX")
        except Exception as exc:  # noqa: BLE001
            self._vulkan_state = False
            logger.info("onnx_embedder: vulkan server unreachable (%s), using ONNX", str(exc)[:80])
        return bool(self._vulkan_state)

    def _fit_for_server(self, text: str, limit: int = 508) -> str:
        """Truncate to the embedding model's context window.

        bge-small's training context is 512 tokens and the server rejects (HTTP
        400) rather than truncating. Chunk bodies target 512 tokens, but
        decode→re-encode is not perfectly idempotent and special tokens add a
        few, so a small safety margin is applied here instead of losing the whole
        document to a fallback. Uses the local tokenizer when present (exact),
        else a conservative character cut.
        """
        try:
            if self._tok_only is None:
                from tokenizers import Tokenizer  # type: ignore
                path = self.model_dir / "tokenizer.json"
                self._tok_only = Tokenizer.from_file(str(path)) if path.exists() else False
            if self._tok_only:
                ids = self._tok_only.encode(text or "").ids[:limit]
                return self._tok_only.decode(ids)
        except Exception:  # noqa: BLE001
            pass
        return (text or "")[:1900]

    def _vulkan_embed_many(self, texts: List[str], is_query: bool = False) -> Optional[List[List[float]]]:
        """Embed via the llama.cpp server (Vulkan). None on any failure.

        Query-side prefixing is preserved so query and document vectors stay in
        the same space as the ONNX path.
        """
        import requests
        out: List[List[float]] = []
        step = max(1, self.vulkan_batch)
        try:
            for i in range(0, len(texts), step):
                chunk = [self._fit_for_server(QUERY_PREFIX + t if is_query else t)
                         for t in texts[i : i + step]]
                started = time.perf_counter()
                r = requests.post(f"{self.embed_server}/v1/embeddings",
                                  json={"input": chunk, "model": "bge"}, timeout=300)
                if r.status_code != 200:
                    # One retry with a harder cut: the server rejects oversize
                    # inputs outright instead of truncating them.
                    chunk = [self._fit_for_server(t, limit=380) for t in chunk]
                    r = requests.post(f"{self.embed_server}/v1/embeddings",
                                      json={"input": chunk, "model": "bge"}, timeout=300)
                    if r.status_code != 200:
                        logger.warning("onnx_embedder: vulkan HTTP %s: %s", r.status_code, r.text[:160])
                        return None
                out.extend(d["embedding"] for d in r.json()["data"])
                self._duty_sleep(time.perf_counter() - started)
        except Exception as exc:  # noqa: BLE001
            logger.warning("onnx_embedder: vulkan embed failed: %s", str(exc)[:160])
            self._vulkan_state = False       # stop retrying this process
            return None
        return out if len(out) == len(texts) else None
    def _wait_resource_headroom(self) -> None:
        if os.environ.get("REALITY_ENGINE_RESOURCE_GUARD", "0") != "1":
            return
        if self._resource_guard is None:
            try:
                from reality_engine.ingestion.resource_guard import ResourceGuard
                self._resource_guard = ResourceGuard.from_env()
            except Exception:
                self._resource_guard = False
        if self._resource_guard:
            self._resource_guard.wait_for_headroom("embed-batch")

    def _duty_sleep(self, work_seconds: float) -> None:
        """Apply GPU duty sleep, then sample CPU/disk/memory headroom."""
        if self.gpu_duty < 1.0 and work_seconds > 0:
            gap = work_seconds * (1.0 / self.gpu_duty - 1.0)
            if gap > 0.005:
                time.sleep(gap)
        self._wait_resource_headroom()

    def embed(self, text: str, is_query: bool = False) -> Optional[List[float]]:
        res = self.embed_many([text or ""], is_query=is_query)
        return res[0] if res else None

    def status(self) -> dict:
        files = self._model_files()
        return {
            "model": MODEL_ID,
            "dimension": DIMENSION,
            "provider": self.provider,
            "available": self.available,
            "model_dir": str(self.model_dir),
            "files_present": bool(files),
        }


# Shared singleton (one ORT session per process).
onnx_embedder = OnnxEmbedder()


def embed_status() -> dict:
    return onnx_embedder.status()
