"""T-242 rule_guard: each "Never" ruling blocks its tool call; everyday calls pass."""
import io
import json

import pytest

from reality_engine.scripts import rule_guard as rg


def bash(cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


def read(path):
    return {"tool_name": "Read", "tool_input": {"file_path": path}}


@pytest.mark.parametrize("call,rule", [
    (read(r"D:\Shivam_Private\Manual Dumps\a.pdf"), "private"),
    (bash("ls 'D:/Shivam_Private/Manual Dumps'"), "private"),
    ({"tool_name": "Glob", "tool_input": {"pattern": "*.pdf", "path": r"C:\Users\warri\Downloads\Telegram Desktop"}},
     "telegram"),
    (read(r"C:\Users\warri\.claude-neo\.credentials.json"), "secrets"),
    (bash("cat ~/.local/share/opencode/auth.json"), "secrets"),
    (bash("echo $OPENCODE_GO_API_KEY"), "secrets"),
    (bash("env | grep KEY"), "secrets"),
    (bash("git push origin Wolf-skills"), "push"),
    (bash("taskkill /F /IM python.exe"), "mass_kill"),
    ({"tool_name": "PowerShell", "tool_input": {"command": "Stop-Process -Name python -Force"}}, "mass_kill"),
    (bash("pkill -f python"), "mass_kill"),
    (bash("python - <<'E'\nimport os; os.listdir(r'C:/Users/warri/Downloads/Telegram Desktop')\nE"), "telegram"),
    (bash("cat > x.txt <<'EOF'\nnotes\nEOF\ngit push origin feature"), "push"),
    (bash("git push"), "push"),
    (bash("git push --force origin dsh/abc"), "push"),
    (bash("opencode run -m opencode/mimo-v2.6-flash-free -f a.png 'x'"), "paid_model"),
    (bash("opencode run -m opencode/hy4-flash-free 'x'"), "paid_model"),
    (bash("opencode run --model deepinfra/google/gemma-4-31B-it 'x'"), "paid_model"),
    (bash("opencode run -m kilo/anthropic/claude-haiku-5.5 'x'"), "paid_model"),
])
def test_blocks(call, rule):
    assert rule in rg.breaches(call)


@pytest.mark.parametrize("call", [
    bash("git push origin main"),
    bash('powershell -NoProfile -Command "Stop-Process -Id 40592,9676 -Force"'),
    bash("taskkill /PID 4321 /F"),
    bash("cd repo; git push -q origin main 2>&1 | tail -2"),
    bash("python - <<'E'\ns='after merge, git push origin x needs OK'\nE"),
    bash("env | grep -c DSH_WORKER_CONTROL_TOKEN"),
    bash("cat >> docs/G.md <<'EOF'\nblocks `Downloads\\Telegram Desktop` and git push\nEOF\ngit add docs/G.md"),
    bash('env | grep -iE "compact|CLAUDE_CODE"'),
    bash("git push --dry-run origin feature"),
    bash("git status && git log --oneline -3"),
    bash("opencode run -m kilo/nvidia/nemotron-3.5-super-vl:free -f a.png 'x'"),
    bash("opencode run -m opencode/nemotron-3.5-super-vl-free 'x'"),
    bash("opencode models | grep -i free"),
    bash("grep -rn deepinfra reality_engine/"),
    bash("python -m reality_engine.v2.observations --reader hy4-flash-free --out x.db"),
    bash("echo done; date"),
    read(r"C:\Users\warri\Downloads\Info_Diffusion_Model\docs\DEVELOPER_GUIDE.md"),
    read(r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\v2\envelope.py"),
    {"tool_name": "Write", "tool_input": {"file_path": "x.py", "content": "Telegram Desktop in text only"}},
])
def test_allows(call):
    assert rg.breaches(call) == []


def test_main_exit_codes(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(bash("git push origin x"))))
    assert rg.main([]) == 2
    assert "RULE push" in capsys.readouterr().err
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(bash("ls"))))
    assert rg.main([]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert rg.main([]) == 0          # a guard bug never blocks work
