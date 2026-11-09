"""Make ``code/`` importable, and provide an in-memory S3 and a packaged cell."""

import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))


class FakeS3:
    """``put_object`` with S3's ``IfNoneMatch`` behaviour; any other call fails the test."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body, IfNoneMatch):
        if Key in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.objects[Key] = Body

    def __getattr__(self, name):
        raise AssertionError(f"upload must not call {name}")


@pytest.fixture
def s3():
    return FakeS3()


@pytest.fixture
def cell(tmp_path):
    folder = tmp_path / "exaSPIM_123456_2026-01-01_00-00-00_reconstruction-N001_2026-02-01_00-00-00"
    for name in (
        "ccf_space_reconstructions/N001-123456-HP.swc",
        "specimen_space_reconstructions/refined/N001-123456-HP.swc",
        "processing.json",
        "data_description.json",
    ):
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(name)
    return folder
