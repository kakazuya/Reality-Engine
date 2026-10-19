"""Create an rclone remote 'gdrive_ro' with READ-ONLY access to the whole Google Drive (2026-10-19).

Why: the existing 'gdrive' remote uses scope drive.file, which only sees files rclone itself created; PDFs and decks
uploaded by hand in the browser are invisible to it, so the upload cannot be checked. This reuses the same OAuth app
(client_id / client_secret of 'gdrive', never printed) and asks Google for drive.readonly: rclone opens a browser,
Shivam signs in and clicks Allow. Nothing on Drive can be changed through this remote.

    python -m reality_engine.scripts.setup_gdrive_readonly
"""
import json
import subprocess
import sys

RCLONE = r"C:\Users\warri\AppData\Local\Microsoft\WinGet\Packages\Rclone.Rclone_Microsoft.Winget.Source_8wekyb3d8bbwe\rclone-v1.75.1-windows-amd64\rclone.exe"


def main():
    cfg = json.loads(subprocess.run([RCLONE, "config", "dump"], capture_output=True, text=True, check=True).stdout)
    if "gdrive_ro" in cfg:
        print("gdrive_ro already exists; testing it")
    else:
        src = cfg.get("gdrive", {})
        args = [RCLONE, "config", "create", "gdrive_ro", "drive", "scope=drive.readonly"]
        if src.get("client_id"):
            args += [f"client_id={src['client_id']}", f"client_secret={src.get('client_secret', '')}"]
        print("A browser window will open: sign in to the Google account that holds InfoDiffusion_archive and click Allow.")
        subprocess.run(args, check=True)
    r = subprocess.run([RCLONE, "lsd", "gdrive_ro:"], capture_output=True, text=True)
    print(r.stdout[-2000:] or r.stderr[-2000:])
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
