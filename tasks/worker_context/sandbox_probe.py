"""Sandbox acceptance probe for Task 03 (run it, then delete the scratch).

It proves, in whatever sandbox the caller is confined to, that
``tempfile.mkdtemp()`` is writable, ``pip install --target .tmp/...`` works and
``npx --version`` runs, with caches inside ``<cwd>/.tmp``.

Claude (unconfined) runs it after installing the staged profiles:

    $ws = "C:\\Users\\warri\\Downloads\\Info_Diffusion_Model\\.tmp\\sandbox-probe"
    New-Item -ItemType Directory -Force "$ws\\.tmp" | Out-Null
    $env:TMP = "$ws\\.tmp"; $env:TEMP = "$ws\\.tmp"; $env:TMPDIR = "$ws\\.tmp"
    $env:PIP_CACHE_DIR = "$ws\\.tmp\\pip-cache"
    $env:npm_config_cache = "$ws\\.tmp\\npm-cache"
    $env:PYTHONPATH = "C:\\Users\\warri\\Downloads\\Info_Diffusion_Model\\plugins\\dsh-worker\\worker_bootstrap"
    python tasks/worker_context/sandbox_probe.py

Then remove ``.tmp/sandbox-probe``.
"""
import os
import subprocess
import sys
import tempfile


def main() -> int:
    print("cwd:", os.getcwd())
    print(
        "TMP/TEMP/TMPDIR:",
        os.environ.get("TMP"),
        os.environ.get("TEMP"),
        os.environ.get("TMPDIR"),
    )
    scratch = tempfile.mkdtemp()
    with open(os.path.join(scratch, "probe.txt"), "w", encoding="utf-8") as handle:
        handle.write("ok")
    print("mkdtemp_ok:", scratch)

    target = os.path.join(os.getcwd(), ".tmp", "pip-target")
    pip = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--target",
            target,
            "six",
            "--disable-pip-version-check",
            "--timeout",
            "60",
            "--retries",
            "2",
        ],
        capture_output=True,
        text=True,
    )
    print("pip_rc:", pip.returncode, (pip.stderr or pip.stdout or "").strip()[-200:])
    print("pip_target_exists:", os.path.isdir(target))

    npx = subprocess.run("npx --version", shell=True, capture_output=True, text=True)
    print("npx_rc:", npx.returncode, npx.stdout.strip(), npx.stderr.strip()[-100:])
    print("PIP_CACHE_DIR:", os.environ.get("PIP_CACHE_DIR"))
    print("npm_config_cache:", os.environ.get("npm_config_cache"))
    return 0 if pip.returncode == 0 and npx.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
