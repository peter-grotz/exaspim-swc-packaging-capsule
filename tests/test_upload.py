"""Tests for upload.py."""

import json

import boto3
import pytest
from botocore.stub import ANY, Stubber

import upload


def files_of(cell):
    return {p.relative_to(cell).as_posix() for p in cell.rglob("*") if p.is_file()}


@pytest.mark.parametrize(
    "destination, prefix",
    [("s3://aind-scratch-data/", ""), ("s3://aind-scratch-data", ""), ("s3://b/x/y/", "x/y/")],
)
def test_each_cell_is_its_own_folder(s3, cell, tmp_path, destination, prefix):
    assert upload.upload_cells(s3, destination, [cell], upload.UPLOAD, tmp_path / "m.json")
    assert set(s3.objects) == {f"{prefix}{cell.name}/{f}" for f in files_of(cell)}


def test_a_dry_run_writes_nothing(s3, cell, tmp_path):
    manifest = tmp_path / "m.json"
    assert upload.upload_cells(s3, "s3://b/", [cell], upload.DRY_RUN, manifest)
    assert not s3.objects
    assert set(json.loads(manifest.read_text())["files"].values()) == {upload.DRY_RUN}


def test_an_existing_object_is_not_replaced(s3, cell, tmp_path):
    key = f"{cell.name}/processing.json"
    s3.objects[key] = b"theirs"
    manifest = tmp_path / "m.json"
    assert not upload.upload_cells(s3, "s3://b/", [cell], upload.UPLOAD, manifest)
    assert s3.objects[key] == b"theirs"
    assert json.loads(manifest.read_text())["files"][key] == "exists"


def test_requests_are_valid_for_the_pinned_botocore(cell, tmp_path):
    client = boto3.client("s3", region_name="us-west-2", aws_access_key_id="x",
                          aws_secret_access_key="x")
    with Stubber(client) as stub:
        for name in sorted(files_of(cell)):
            stub.add_response("put_object", {}, {"Bucket": "b", "Key": f"{cell.name}/{name}",
                                                 "Body": ANY, "IfNoneMatch": "*"})
        assert upload.upload_cells(client, "s3://b/", [cell], upload.UPLOAD, tmp_path / "m.json")
        stub.assert_no_pending_responses()
