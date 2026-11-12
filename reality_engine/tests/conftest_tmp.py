import os, tempfile, shutil
import pytest

@pytest.fixture
def tmp_path():
    d = tempfile.mkdtemp(dir=os.environ.get('TMP', '.tmp'))
    p = __import__('pathlib').Path(d)
    yield p
    # no cleanup to avoid ACL issues
