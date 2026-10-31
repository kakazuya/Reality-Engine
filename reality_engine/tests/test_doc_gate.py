from reality_engine.scripts.doc_gate import check


def test_merge_on_main_needs_state():
    assert check(["reality_engine/x.py", "a.md"], branch="main", merging=True)
    assert check(["reality_engine/x.py", "tasks/STATE.md"], branch="main", merging=True) is None


def test_code_commit_on_main_needs_a_doc():
    assert check(["reality_engine/x.py"], branch="main", merging=False)
    assert check(["reality_engine/x.py", "tasks/dsh_tasks/BRIEF.md"], branch="main", merging=False)
    assert check(["reality_engine/x.py", "tasks/arch_v4/REPORT.md"], branch="main", merging=False) is None


def test_docs_alone_and_worker_branches_pass():
    assert check(["tasks/dsh_tasks/BRIEF.md"], branch="main", merging=False) is None
    assert check(["reality_engine/x.py"], branch="dsh/20261031T000000Z-abc", merging=False) is None
