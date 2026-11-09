"""Make the capsule's ``code/`` importable, and provide an in-memory S3."""

import base64
import hashlib
import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))


def _error(code: str, operation: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


class FakeS3:
    """The calls the upload makes, with S3's conditional-write and checksum behaviour."""

    def __init__(self):
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.puts: list[str] = []

    def head_object(self, Bucket, Key, ChecksumMode):
        if Key not in self.objects:
            raise _error("404", "HeadObject")
        checksum = self.objects[Key][1]
        return {"ChecksumSHA256": checksum} if checksum else {}

    def put_object(self, Bucket, Key, Body, IfNoneMatch, ChecksumSHA256):
        assert IfNoneMatch == "*"
        if Key in self.objects:
            raise _error("PreconditionFailed", "PutObject")
        assert ChecksumSHA256 == base64.b64encode(hashlib.sha256(Body).digest()).decode()
        self.objects[Key] = (Body, ChecksumSHA256)
        self.puts.append(Key)

    def __getattr__(self, name):
        raise AssertionError(f"upload must not call {name}")


@pytest.fixture
def s3():
    return FakeS3()


@pytest.fixture
def cell(tmp_path):
    """A packaged cell directory in the layout packaging writes."""
    folder = tmp_path / "exaSPIM_123456_2026-01-01_00-00-00_reconstruction-N001_2026-02-01_00-00-00"
    for name, text in {
        "ccf_space_reconstructions/N001-123456-HP.swc": "1 1 0 0 0 1 -1\n",
        "specimen_space_reconstructions/refined/N001-123456-HP.swc": "1 1 5 5 5 1 -1\n",
        "processing.json": "{}",
        "data_description.json": "{}",
    }.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text)
    return folder
