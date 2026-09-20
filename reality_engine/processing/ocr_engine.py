"""Optional-accelerated OCR with deterministic financial entity extraction."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("reality_engine.ocr_engine")


class FinancialOCREngine:
    def __init__(self, confidence_threshold: float = 0.60, use_rapidocr: bool = True, prefer_gpu: bool = True):
        self.confidence_threshold = confidence_threshold
        # Engine construction imports onnxruntime/rapidocr and probes execution providers
        # (~1.2s). Every process that merely imported the ingestion stack used to pay it at
        # import time. It now happens on first use.
        #
        # ``engine`` and ``provider`` are lazy properties so the existing availability
        # probes (`inst.engine is not None`, `inst.provider`) still report the truth
        # instead of a pre-init stub -- they simply trigger construction when asked.
        self._use_rapidocr = use_rapidocr
        self._prefer_gpu = prefer_gpu
        self._engine = None
        self._provider = "NONE"
        self._v3 = False
        self._initialized = False

    def _ensure_engine(self) -> None:
        """Build the OCR engine on first use. Idempotent; failures degrade to no engine."""
        if self._initialized:
            return
        # Set before building: the builders read/write self.engine (the property), and this
        # flag is what stops that read from recursing back into _ensure_engine.
        self._initialized = True
        if not self._use_rapidocr:
            return
        try:
            # RapidOCR v3 (rapidocr package): DirectML-compatible (AMD RX 6700 XT via D3D12)
            try:
                from rapidocr import RapidOCR
                self._build_engine_v3(RapidOCR, self._prefer_gpu)
                self._v3 = True
            except ImportError:
                self._v3 = False
            if self._engine is None:
                # Legacy rapidocr_onnxruntime fallback (v1.x)
                from rapidocr_onnxruntime import RapidOCR as _LegacyRapidOCR
                self._build_engine_legacy(_LegacyRapidOCR)
                self._v3 = False
        except ImportError:
            self._engine = None

    @property
    def engine(self):
        self._ensure_engine()
        return self._engine

    @engine.setter
    def engine(self, value) -> None:
        self._engine = value

    @property
    def provider(self) -> str:
        self._ensure_engine()
        return self._provider

    @provider.setter
    def provider(self, value) -> None:
        self._provider = value

    def _gpu_available(self) -> bool:
        try:
            import onnxruntime as ort
            providers = ort.get_available_providers()
            return "DmlExecutionProvider" in providers or "CUDAExecutionProvider" in providers
        except (ImportError, Exception):
            return False

    def _build_engine_v3(self, RapidOCR, prefer_gpu: bool) -> None:
        """Build RapidOCR v3 engine preferring DirectML/CUDA EP with CPU fallback."""
        try:
            if prefer_gpu and self._gpu_available():
                import onnxruntime as ort
                providers = ort.get_available_providers()
                if "DmlExecutionProvider" in providers:
                    # RapidOCR v3: EngineConfig.onnxruntime.use_dml (DirectML / D3D12)
                    # small tables -> cap max_side_len to shrink det input, boost latency
                    try:
                        params = {
                            "EngineConfig.onnxruntime.use_dml": True,
                            "Global.log_level": "ERROR",
                            "Global.max_side_len": 1024,
                        }
                        self.engine = RapidOCR(params=params)
                        self.provider = "DML (DirectML)"
                        logger.info("OCR engine initialized with DirectML provider (AMD GPU D3D12)")
                        return
                    except Exception as dml_exc:
                        logger.warning("RapidOCR v3 DirectML init failed (%s); trying CUDA/default", dml_exc)
                if "CUDAExecutionProvider" in providers:
                    params = {
                        "EngineConfig.onnxruntime.use_cuda": True,
                        "Global.log_level": "ERROR",
                    }
                    try:
                        self.engine = RapidOCR(params=params)
                        self.provider = "CUDA"
                        logger.info("OCR engine initialized with CUDA provider")
                        return
                    except Exception as cuda_exc:
                        logger.warning("RapidOCR v3 CUDA init failed (%s); falling back to CPU", cuda_exc)
            self.engine = RapidOCR(params={"Global.log_level": "ERROR"})
            self.provider = "CPU"
            logger.info("OCR engine initialized with CPU provider (fallback)")
        except Exception as exc:
            logger.warning("RapidOCR v3 init failed (%s); falling back to default", exc)
            try:
                self.engine = RapidOCR()
                self.provider = "CPU"
            except Exception as exc2:
                logger.warning("RapidOCR v3 default init failed: %s", exc2)
                self.engine = None

    def _build_engine_legacy(self, RapidOCR) -> None:
        """Build legacy rapidocr_onnxruntime v1 engine (CUDA if available, else CPU only)."""
        try:
            self.engine = RapidOCR()
            self.provider = "CPU"  # legacy v1 has no DML support
            logger.info("OCR engine initialized (legacy rapidocr_onnxruntime, CPU only)")
        except Exception as exc:
            logger.warning("Legacy RapidOCR init failed: %s", exc)
            self.engine = None

    @staticmethod
    def preprocess(image: Any) -> Any:
        try:
            import cv2  # type: ignore
            import numpy as np
            array = np.asarray(image.convert("RGB") if hasattr(image, "convert") else image)
            gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY) if len(array.shape) == 3 else array
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            return clahe.apply(gray)
        except (ImportError, AttributeError, ValueError):
            return image

    def _read_text(self, path: str | Path) -> tuple[str, float]:
        start = time.perf_counter()
        image = None
        try:
            from PIL import Image  # type: ignore
            with Image.open(path) as img:
                image = img.copy()
        except (ImportError, Exception):
            pass
        if self.engine and image is not None:
            # RapidOCR v3 returns RapidOCROutput; legacy v1 returns (results, elapse)
            output = self.engine(self.preprocess(image))
            if output is None:
                return "", 0.0
            if hasattr(output, "txts") and hasattr(output, "scores"):
                txts = output.txts or ()
                scores = output.scores or ()
                lines = [
                    (str(t), float(s))
                    for t, s in zip(txts, scores)
                    if float(s) >= self.confidence_threshold
                ]
                return "\n".join(x[0] for x in lines), (sum(x[1] for x in lines) / len(lines)) if lines else 0.0
            # Legacy tuple format (result, elapse)
            try:
                result, _ = output
                items = result or []
                lines = [
                    (str(item[1]), float(item[2]))
                    for item in items
                    if len(item) >= 3 and float(item[2]) >= self.confidence_threshold
                ]
                return "\n".join(x[0] for x in lines), (sum(x[1] for x in lines) / len(lines)) if lines else 0.0
            except (TypeError, ValueError, IndexError):
                logger.warning("Unexpected OCR engine output format: %r", type(output))
                return "", 0.0
        try:
            import pytesseract  # type: ignore
            return pytesseract.image_to_string(image or path, config="--oem 1 -l eng"), 0.75
        except (ImportError, Exception):
            return "", 0.0

    @staticmethod
    def extract_entities(text: str) -> dict[str, Any]:
        number = r"(?:₹|INR|Rs\.?|रु\.?)?\s*([0-9]+(?:\.[0-9]+)?)"
        def values(labels: str) -> list[float]:
            return [float(v) for v in re.findall(rf"(?:{labels})\s*[:=\-]?\s*{number}", text, re.I)]
        candidates = sorted(set(re.findall(r"\b[A-Z]{3,12}\b", text)))
        return {"ticker_candidates": candidates, "price_targets": values(r"target|tgt|buy above|breakout"), "stop_losses": values(r"stop\s*loss|SL"), "commentary": text}

    def process_image(self, image_path: str | Path) -> dict[str, Any]:
        start = time.perf_counter()
        text, confidence = self._read_text(image_path)
        result = {"raw_text": text, "avg_confidence": confidence, "inference_time_ms": (time.perf_counter() - start) * 1000}
        result.update(self.extract_entities(text))
        result["tickers"] = result["ticker_candidates"]
        return result
