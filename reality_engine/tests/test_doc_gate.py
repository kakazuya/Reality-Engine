from reality_engine.scripts.doc_gate import check

NAMES_X = {"tasks/arch_v4/REPORT.md": "see reality_engine/x.py", "tasks/STATE.md": "x.py merged", "a.md": "other"}.get


def read(name):
    return NAMES_X(name, "")


def test_merge_on_main_needs_state():
    assert check(["reality_engine/x.py", "tasks/arch_v4/REPORT.md"], branch="main", merging=True, read=read)
    assert check(["reality_engine/x.py", "tasks/arch_v4/REPORT.md", "tasks/STATE.md"], branch="main", merging=True, read=read) is None


def test_state_alone_does_not_document_a_merge():
    assert check(["reality_engine/x.py", "tasks/STATE.md"], branch="main", merging=True, read=read)


def test_merge_doc_must_name_the_code():
    assert check(["reality_engine/x.py", "a.md", "tasks/STATE.md"], branch="main", merging=True, read=read)


def test_code_commit_on_main_needs_a_doc_naming_it():
    assert check(["reality_engine/x.py"], branch="main", merging=False, read=read)
    assert check(["reality_engine/x.py", "tasks/dsh_tasks/BRIEF.md"], branch="main", merging=False, read=read)
    assert check(["reality_engine/x.py", "a.md"], branch="main", merging=False, read=read)
    assert check(["reality_engine/x.py", "tasks/arch_v4/REPORT.md"], branch="main", merging=False, read=read) is None


def test_tests_need_no_doc():
    assert check(["reality_engine/tests/test_x.py"], branch="main", merging=False, read=read) is None


def test_docs_alone_and_worker_branches_pass():
    assert check(["tasks/dsh_tasks/BRIEF.md"], branch="main", merging=False) is None
    assert check(["reality_engine/x.py"], branch="dsh/20261031T000000Z-abc", merging=False) is None
