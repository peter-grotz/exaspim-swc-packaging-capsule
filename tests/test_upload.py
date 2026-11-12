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
    assert upload.upload_cells(s3, destination, [cell], tmp_path / "m.json")
    assert set(s3.objects) == {f"{prefix}{cell.name}/{f}" for f in files_of(cell)}


def test_no_destination_is_a_dry_run(cell, tmp_path):
    manifest = tmp_path / "m.json"
    assert upload.upload_cells(None, "", [cell], manifest)
    files = json.loads(manifest.read_text())["files"]
    assert files == {f"{cell.name}/{f}": upload.DRY_RUN for f in files_of(cell)}


def test_an_existing_object_is_not_replaced(s3, cell, tmp_path):
    key = f"{cell.name}/processing.json"
    s3.objects[key] = b"theirs"
    manifest = tmp_path / "m.json"
    assert not upload.upload_cells(s3, "s3://b/", [cell], manifest)
    assert s3.objects[key] == b"theirs"
    assert json.loads(manifest.read_text())["files"][key] == "exists"


def test_json_and_precomputed_info_files_are_served_as_json(s3, cell, tmp_path):
    assert upload.upload_cells(s3, "s3://b/", [cell], tmp_path / "m.json")
    precomputed = f"{cell.name}/ccf_space_reconstructions/reconstructions.precomputed"
    assert s3.content_types[f"{precomputed}/info"] == upload.JSON
    assert s3.content_types[f"{precomputed}/segment_properties/info"] == upload.JSON
    assert s3.content_types[f"{cell.name}/processing.json"] == upload.JSON
    assert s3.content_types[f"{precomputed}/1"] == upload.BINARY
    assert s3.content_types[f"{cell.name}/ccf_space_reconstructions/N001-123456.swc"] == (
        upload.BINARY
    )


def test_requests_are_valid_for_the_pinned_botocore(cell, tmp_path):
    client = boto3.client("s3", region_name="us-west-2", aws_access_key_id="x",
                          aws_secret_access_key="x")
    with Stubber(client) as stub:
        for name in sorted(files_of(cell)):
            stub.add_response("put_object", {}, {"Bucket": "b", "Key": f"{cell.name}/{name}",
                                                 "Body": ANY, "ContentType": ANY,
                                                 "IfNoneMatch": "*"})
        assert upload.upload_cells(client, "s3://b/", [cell], tmp_path / "m.json")
        stub.assert_no_pending_responses()
