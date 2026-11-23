import shutil
import uuid
from pathlib import Path

import pytest

from reality_engine.scripts.doc_gate import REVIEWS, check


@pytest.fixture()
def root():
    """A writable dir in the checkout; the machine's temp base is not writable in the sandbox."""
    path = Path.cwd() / f"_doc_gate_test_{uuid.uuid4().hex[:12]}"
    path.mkdir()
    yield path
    shutil.rmtree(path, ignore_errors=True)

NAMES_X = {"tasks/arch_v4/REPORT.md": "see reality_engine/x.py", "tasks/STATE.md": "x.py merged", "a.md": "other"}.get


def read(name):
    return NAMES_X(name, "")


def test_merge_on_main_needs_state():
    assert check(["reality_engine/x.py", "tasks/arch_v4/REPORT.md"], branch="main", merging=True, read=read, added="")
    assert check(["reality_engine/x.py", "tasks/arch_v4/REPORT.md", "tasks/STATE.md"], branch="main", merging=True, read=read, added="") is None


def test_state_alone_does_not_document_a_merge():
    assert check(["reality_engine/x.py", "tasks/STATE.md"], branch="main", merging=True, read=read, added="")


def test_merge_doc_must_name_the_code():
    assert check(["reality_engine/x.py", "a.md", "tasks/STATE.md"], branch="main", merging=True, read=read, added="")


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


def test_start_files_have_line_limits():
    def lines(n):
        return lambda name: chr(10).join(["x"] * n)

    refused = check(["tasks/STATE.md"], branch="main", merging=False, read=lines(41))
    assert refused and "limit 40" in refused
    assert check(["AGENTS.md"], branch="main", merging=False, read=lines(41)) is None
    refused = check(["AGENTS.md"], branch="main", merging=False, read=lines(151))
    assert refused and "limit 150" in refused


def test_start_files_have_character_limits():
    def chars(n):
        return lambda name: "x" * n

    refused = check(["tasks/STATE.md"], branch="main", merging=False, read=chars(4001))
    assert refused and "4001 characters, limit 4000" in refused
    assert check(["tasks/STATE.md"], branch="main", merging=False, read=chars(4000)) is None
    refused = check(["tasks/RULINGS.md"], branch="main", merging=False, read=chars(8001))
    assert refused and "8001 characters, limit 8000" in refused
    assert check(["tasks/RULINGS.md"], branch="main", merging=False, read=chars(8000)) is None


def test_commit_message_with_an_invented_ticket_is_refused_on_main():
    from reality_engine.scripts.doc_gate import check_message

    assert check_message("work T-999", branch="main", known={"T-001"})
    assert check_message("work T-001", branch="main", known={"T-001"}) is None
    assert check_message("No-ticket: typo", branch="main", known={"T-001"}) is None
    assert check_message("work T-999", branch="dsh/x", known={"T-001"}) is None


# -- Gate A (T-127): a merge of a worker branch needs that job's review row ---------------

JOB = "20261108T114201Z-41e0aa80"
BRANCH = f"dsh/{JOB}"
REVIEW = '{"id": "%s", "job_type": "code"}' % JOB
STAGED_MERGE = ["a.md", "tasks/STATE.md"]


def reviews(text):
    def reader(name):
        return text if name == REVIEWS else NAMES_X(name, "")

    return reader


def test_merge_of_a_dsh_branch_needs_a_worker_review_row(root):
    path = root / REVIEWS
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")
    refused = check(STAGED_MERGE, branch="main", merging=True, read=reviews(""), merge_branch=BRANCH, root=root)
    assert refused == f"merge of {BRANCH} without a worker review row in {REVIEWS}"
    path.write_text(REVIEW + "\n", encoding="utf-8")
    assert check(STAGED_MERGE, branch="main", merging=True, read=reviews(""),
                 merge_branch=BRANCH, root=root) is None
    # a malformed line does not hide the real row
    path.write_text("not json\n" + REVIEW, encoding="utf-8")
    assert check(STAGED_MERGE, branch="main", merging=True, read=reviews(""),
                 merge_branch=BRANCH, root=root) is None
    # the staged copy is used when the file is staged, the working copy otherwise
    path.write_text("", encoding="utf-8")
    assert check(STAGED_MERGE + [REVIEWS], branch="main", merging=True, read=reviews(REVIEW),
                 merge_branch=BRANCH, root=root) is None


def test_unreadable_reviews_file_is_refused_with_its_reason(root):
    refused = check(STAGED_MERGE, branch="main", merging=True, read=reviews(""),
                    merge_branch=BRANCH, root=root / "missing")
    assert refused and "without a worker review row" in refused and "cannot be read" in refused


def test_non_dsh_merges_are_unaffected_by_the_review_gate(root):
    assert check(STAGED_MERGE, branch="main", merging=True, read=reviews(""),
                 merge_branch=None, root=root) is None
    assert check(STAGED_MERGE, branch="main", merging=True, read=reviews(""),
                 merge_branch="feature/other", root=root) is None


# -- Gate B (T-127): a merge that adds code needs a staged test ---------------------------

STAGED_CODE = ["reality_engine/x.py", "tasks/arch_v4/REPORT.md", "tasks/STATE.md"]
NEW_DEF = "@@ -1,0 +2,1 @@\n+def new_thing():\n"


def test_merge_adding_a_new_top_level_def_needs_a_test():
    refused = check(STAGED_CODE, branch="main", merging=True, read=read, added=NEW_DEF)
    assert refused and "reality_engine/x.py" in refused and "without a test" in refused
    assert check(STAGED_CODE + ["reality_engine/tests/test_x.py"], branch="main", merging=True,
                 read=read, added=NEW_DEF) is None
    assert check(STAGED_CODE + ["plugins/dsh-worker/tests/test_x.py"], branch="main", merging=True,
                 read=read, added=NEW_DEF) is None


def test_pure_fix_needs_no_test():
    assert check(STAGED_CODE, branch="main", merging=True, read=read, added="@@\n-    return 1\n+    return 2\n") is None
    # a method is not a top-level def
    assert check(STAGED_CODE, branch="main", merging=True, read=read, added="+    def helper(self):\n") is None


def test_merge_tests_gate_only_applies_to_merges():
    assert check(["reality_engine/x.py", "tasks/arch_v4/REPORT.md"], branch="main", merging=False,
                 read=read, added=NEW_DEF) is None
    assert check(["reality_engine/x.py", "tasks/arch_v4/REPORT.md"], branch="dsh/20261031T000000Z-abc",
                 merging=True, read=read, added=NEW_DEF) is None


def test_gate_rules_are_named_for_the_ledger():
    from reality_engine.scripts.doc_gate import gate_rule

    assert gate_rule(f"merge of {BRANCH} without a worker review row in {REVIEWS}") == "worker_review"
    assert gate_rule("merge adds code without a test: reality_engine/x.py") == "merge_tests"
