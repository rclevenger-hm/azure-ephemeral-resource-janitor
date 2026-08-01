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
