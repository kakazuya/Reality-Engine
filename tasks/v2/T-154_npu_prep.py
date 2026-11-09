"""T-154: make an exported encoder runnable on the Snapdragon X NPU (QNN HTP) and time it (prototype, Opus).

The HTP backend only takes whole graphs with fixed shapes; a dynamic-shape FP32 graph falls back to the CPU
(9 Nov: bge-small 5.2 pages/s on "NPU" = CPU speed).  Steps, all in onnxruntime (no AI Hub):
  fixed   batch x seq fixed (8 x 512)                          -> model_fixed.onnx   (try HTP FP16)
  qdq     + QNN pre-processing + static QDQ quantisation       -> model_qdq.onnx     (uint16 act / uint8 weight,
          calibrated on 64 corpus pages)
  bench   time N pages on cpu | htp-fixed | htp-qdq, print the share of nodes the QNN EP took

    python T-154_npu_prep.py <onnx dir> fixed|qdq|bench [variant]
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

B, S = 8, 512


def feeds(d: Path, texts):
    from tokenizers import Tokenizer
    tok = Tokenizer.from_file(str(d / "tokenizer.json"))
    tok.enable_truncation(S)
    tok.enable_padding(length=S)
    names = json.load(open(d / "inputs.json"))["inputs"]
    enc = tok.encode_batch(texts)
    f = {"input_ids": np.array([e.ids for e in enc], dtype=np.int64),
         "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64)}
    if "token_type_ids" in names:
        f["token_type_ids"] = np.array([e.type_ids for e in enc], dtype=np.int64)
    return f


def pages(n):
    out = []
    for line in open(Path(__file__).with_name("corpus.jsonl"), encoding="utf-8"):
        out.append(json.loads(line)["text"])
        if len(out) >= n:
            break
    return out


def fixed(d: Path) -> None:
    import onnx
    from onnxruntime.tools.onnx_model_utils import make_dim_param_fixed, fix_output_shapes
    m = onnx.load(str(d / "model.onnx"))
    make_dim_param_fixed(m.graph, "batch", B)
    make_dim_param_fixed(m.graph, "seq", S)
    fix_output_shapes(m)
    onnx.save(m, str(d / "model_fixed.onnx"), save_as_external_data=m.ByteSize() > 1.9e9)
    print("wrote", d / "model_fixed.onnx")


def qdq(d: Path) -> None:
    from onnxruntime.quantization import CalibrationDataReader, QuantType, quantize
    from onnxruntime.quantization.execution_providers.qnn import get_qnn_qdq_config, qnn_preprocess_model
    src, pre = d / "model_fixed.onnx", d / "model_pre.onnx"
    if not qnn_preprocess_model(str(src), str(pre)):
        pre = src
    texts = pages(64)

    class Reader(CalibrationDataReader):
        def __init__(self):
            self.it = iter([feeds(d, texts[i:i + B]) for i in range(0, len(texts), B)])

        def get_next(self):
            return next(self.it, None)

    cfg = get_qnn_qdq_config(str(pre), Reader(), activation_type=QuantType.QUInt16, weight_type=QuantType.QUInt8)
    quantize(str(pre), str(d / "model_qdq.onnx"), cfg)
    print("wrote", d / "model_qdq.onnx")


def session(d: Path, variant: str):
    import onnxruntime as ort
    so = ort.SessionOptions()
    if variant == "cpu":
        return ort.InferenceSession(str(d / "model_fixed.onnx"), so, providers=["CPUExecutionProvider"])
    import onnxruntime_qnn
    ort.register_execution_provider_library("QNNExecutionProvider", onnxruntime_qnn.get_library_path())
    devs = [x for x in ort.get_ep_devices() if x.ep_name == "QNNExecutionProvider" and "NPU" in str(x.device.type)]
    opts = {"htp_performance_mode": "burst"}
    if variant == "htp-fixed":
        opts["enable_htp_fp16_precision"] = "1"
    so.add_provider_for_devices(devs, opts)
    so.add_session_config_entry("session.disable_cpu_ep_fallback", "0")
    path = d / ("model_qdq.onnx" if variant == "htp-qdq" else "model_fixed.onnx")
    return ort.InferenceSession(str(path), so)


def bench(d: Path, variant: str, n: int = 160) -> None:
    t0 = time.time()
    sess = session(d, variant)
    load = time.time() - t0
    texts = pages(n)
    sess.run(None, feeds(d, texts[:B]))                       # warm-up / graph finalise
    t1 = time.time()
    for i in range(0, n, B):
        sess.run(None, feeds(d, texts[i:i + B]))
    secs = time.time() - t1
    print(json.dumps({"dir": d.name, "variant": variant, "load_s": round(load, 1), "pages": n,
                      "pages_per_second": round(n / secs, 1)}), flush=True)


if __name__ == "__main__":
    d, cmd = Path(sys.argv[1]), sys.argv[2]
    {"fixed": lambda: fixed(d), "qdq": lambda: qdq(d),
     "bench": lambda: bench(d, sys.argv[3])}[cmd]()
