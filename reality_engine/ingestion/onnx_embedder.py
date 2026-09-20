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
import threading
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
        batch_size: int = 32,
    ):
        self.model_dir = Path(model_dir) if model_dir else default_model_dir()
        self.prefer_gpu = prefer_gpu
        self.batch_size = max(1, int(batch_size))
        self._lock = threading.Lock()
        self._session = None
        self._tokenizer = None
        self._provider: Optional[str] = None
        self._probed = False
        self._available: Optional[bool] = None

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
        if not self._ensure():
            return None
        out: List[List[float]] = []
        flags = [is_query] * len(texts)
        with self._lock:  # DML Run is sequential per session (ORT DirectML doc)
            for i in range(0, len(texts), self.batch_size):
                try:
                    out.extend(self._encode_batch(texts[i : i + self.batch_size], flags[i : i + self.batch_size]))
                except Exception as exc:
                    logger.warning("onnx_embedder: batch miss (%d texts): %s", len(texts), exc)
                    return None
        return out

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
