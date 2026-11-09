"""Upload never overwrites, never deletes, and writes metadata last."""

import json

import boto3
import pytest
from botocore.stub import ANY, Stubber

import upload
from conftest import _error as conftest_error

DEST = "s3://aind-scratch-data/exaspim/"


def run(s3, cells, mode, tmp_path):
    manifest = tmp_path / "manifest.json"
    ok = upload.upload_cells(s3, DEST, cells, mode, manifest)
    return ok, json.loads(manifest.read_text())["files"]


def test_destination_is_split_into_bucket_and_prefix():
    assert upload.parse_destination("s3://b/a/c") == ("b", "a/c/")
    assert upload.parse_destination("s3://b") == ("b", "")
    with pytest.raises(ValueError):
        upload.parse_destination("aind-scratch-data/x")


def test_a_cell_is_uploaded_as_its_own_folder_with_metadata_last(s3, cell, tmp_path):
    ok, files = run(s3, [cell], upload.UPLOAD, tmp_path)
    assert ok and {f["status"] for f in files} == {upload.UPLOADED}
    assert all(k.startswith(f"exaspim/{cell.name}/") for k in s3.puts)
    last_two = [k.rsplit("/", 1)[1] for k in s3.puts[-2:]]
    assert last_two == ["processing.json", "data_description.json"]


@pytest.mark.parametrize(
    "destination, prefix",
    [("s3://aind-scratch-data/", ""), ("s3://aind-scratch-data", ""), ("s3://b/x/y/", "x/y/")],
)
def test_every_key_is_inside_the_cell_folder(s3, cell, tmp_path, destination, prefix):
    assert upload.upload_cells(s3, destination, [cell], upload.UPLOAD, tmp_path / "m.json")
    expected = {f"{prefix}{cell.name}/{p.relative_to(cell).as_posix()}" for p in cell.rglob("*")
                if p.is_file()}
    assert set(s3.puts) == set(s3.objects) == expected


def test_a_dry_run_writes_nothing(s3, cell, tmp_path):
    ok, files = run(s3, [cell], upload.DRY_RUN, tmp_path)
    assert ok and not s3.puts and {f["status"] for f in files} == {upload.WOULD_UPLOAD}


def test_a_rerun_skips_identical_files(s3, cell, tmp_path):
    run(s3, [cell], upload.UPLOAD, tmp_path)
    s3.puts.clear()
    ok, files = run(s3, [cell], upload.UPLOAD, tmp_path)
    assert ok and not s3.puts and {f["status"] for f in files} == {upload.SKIPPED}


def test_a_partial_upload_is_completed_on_rerun(s3, cell, tmp_path):
    run(s3, [cell], upload.UPLOAD, tmp_path)
    del s3.objects[f"exaspim/{cell.name}/data_description.json"]
    s3.puts.clear()
    ok, _ = run(s3, [cell], upload.UPLOAD, tmp_path)
    assert ok and s3.puts == [f"exaspim/{cell.name}/data_description.json"]


@pytest.mark.parametrize("stored", ["other-checksum", ""])
def test_a_different_or_unverifiable_object_stops_the_cell(s3, cell, tmp_path, stored):
    key = f"exaspim/{cell.name}/processing.json"
    s3.objects[key] = (b"theirs", stored)
    ok, files = run(s3, [cell], upload.UPLOAD, tmp_path)
    assert not ok and not s3.puts
    assert s3.objects[key] == (b"theirs", stored)
    assert [f["status"] for f in files if f["key"] == key] == [upload.CONFLICT]


def test_an_object_appearing_mid_upload_is_not_overwritten(s3, cell, tmp_path, monkeypatch):
    key = f"exaspim/{cell.name}/processing.json"

    def racing_put(**kwargs):
        if kwargs["Key"] == key:
            s3.objects[key] = (b"theirs", "x")
        return type(s3).put_object(s3, **kwargs)

    monkeypatch.setattr(s3, "put_object", racing_put)
    ok, files = run(s3, [cell], upload.UPLOAD, tmp_path)
    assert not ok and s3.objects[key] == (b"theirs", "x")
    assert files[-1]["status"] == upload.CONFLICT


def test_requests_are_valid_for_the_pinned_botocore(cell):
    client = boto3.client(
        "s3", region_name="us-west-2", aws_access_key_id="x", aws_secret_access_key="x"
    )
    with Stubber(client) as stub:
        for path in upload.cell_files(cell):
            key = f"exaspim/{cell.name}/{path.relative_to(cell).as_posix()}"
            stub.add_client_error("head_object", "404", http_status_code=404,
                                  expected_params={"Bucket": "aind-scratch-data", "Key": key,
                                                   "ChecksumMode": "ENABLED"})
        for path in upload.cell_files(cell):
            key = f"exaspim/{cell.name}/{path.relative_to(cell).as_posix()}"
            stub.add_response("put_object", {}, {"Bucket": "aind-scratch-data", "Key": key,
                                                 "Body": ANY, "IfNoneMatch": "*",
                                                 "ChecksumSHA256": upload.sha256_b64(path)})
        entries = upload.upload_cell(client, "aind-scratch-data", "exaspim/", cell, dry_run=False)
        stub.assert_no_pending_responses()
    assert {e.status for e in entries} == {upload.UPLOADED}


def test_the_manifest_is_written_when_access_is_denied(s3, cell, tmp_path, monkeypatch):
    def denied(**_kwargs):
        raise conftest_error("AccessDenied", "PutObject")

    monkeypatch.setattr(s3, "put_object", denied)
    manifest = tmp_path / "manifest.json"
    assert not upload.upload_cells(s3, DEST, [cell], upload.UPLOAD, manifest)
    files = json.loads(manifest.read_text())["files"]
    assert files[-1]["status"] == upload.ERROR and not s3.objects

