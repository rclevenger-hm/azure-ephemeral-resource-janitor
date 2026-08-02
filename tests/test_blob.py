import json

import responses
from conftest import Credential

from janitor.blob import BlobObjects


def endpoint(policy, key="state.json"):
    return f"{policy.blob_url}/{policy.state_container}/{key}"


@responses.activate
def test_create_uses_if_none_match(policy):
    responses.put(endpoint(policy), status=201, headers={"ETag": '"v1"'})
    objects = BlobObjects.connect(policy, Credential())
    assert objects.write("state.json", {"schema": 1}, 0) == '"v1"'
    request = responses.calls[0].request
    assert request.headers["If-None-Match"] == "*"
    assert request.headers["x-ms-blob-content-type"] == "application/json"
    assert json.loads(request.body) == {"schema": 1}


@responses.activate
def test_replace_and_delete_require_current_etag(policy):
    url = endpoint(policy)
    responses.put(url, status=201, headers={"ETag": '"v2"'})
    responses.delete(url, status=202)
    objects = BlobObjects.connect(policy, Credential())
    assert objects.write("state.json", {}, '"v1"') == '"v2"'
    objects.delete("state.json", '"v2"')
    assert [c.request.headers["If-Match"] for c in responses.calls] == ['"v1"', '"v2"']


@responses.activate
def test_read_pins_download_to_observed_etag(policy):
    body = b'{"schema": 1}'
    responses.head(endpoint(policy), headers={"ETag": '"v1"', "Content-Length": str(len(body))})
    responses.get(
        endpoint(policy),
        body=body,
        headers={
            "ETag": '"v1"',
            "Content-Length": str(len(body)),
            "Content-Range": f"bytes 0-{len(body) - 1}/{len(body)}",
        },
        status=206,
    )
    assert BlobObjects.connect(policy, Credential()).read("state.json") == ({"schema": 1}, '"v1"')
    assert responses.calls[1].request.headers["If-Match"] == '"v1"'


@responses.activate
def test_missing_blob_has_create_generation(policy):
    responses.head(endpoint(policy), status=404, headers={"x-ms-error-code": "BlobNotFound"})
    assert BlobObjects.connect(policy, Credential()).read("state.json") == (None, 0)
