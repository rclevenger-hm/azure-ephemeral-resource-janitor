from dataclasses import replace

import pytest
import requests
import responses
from conftest import SUB, Credential

from janitor.config import ConfigError
from janitor.transport import ARM, APIError, ARMClient


@pytest.fixture
def client(policy):
    return ARMClient(policy, Credential(), requests.Session())


@pytest.mark.parametrize(
    "url",
    [
        "https://attacker.invalid/path",
        f"http://management.azure.com/subscriptions/{SUB}",
        "https://management.azure.com/subscriptions/99999999-2222-3333-4444-555555555555/resources",
        f"https://management.azure.com/subscriptions/{SUB}/../other",
        f"https://management.azure.com/subscriptions/{SUB}/%2e%2e/other",
        f"https://management.azure.com@attacker.invalid/subscriptions/{SUB}",
        f"https://management.azure.com/subscriptions/{SUB}evil/resources",
    ],
)
def test_token_never_sent_to_untrusted_host_or_scope(client, url):
    with pytest.raises(ConfigError):
        client.get("resources", url)


@responses.activate
def test_pagination_follows_same_collection(client):
    path = (
        f"/subscriptions/{SUB}/resourcegroups/ephemeral/providers/microsoft.compute/virtualmachines"
    )
    next_url = ARM + path + "?api-version=2025-04-01&$skiptoken=page2"
    responses.get(ARM + path, json={"value": [{"id": "one"}], "nextLink": next_url})
    responses.get(next_url, json={"value": [{"id": "two"}]})
    assert list(client.pages("compute", path)) == [{"id": "one"}, {"id": "two"}]


@responses.activate
def test_pagination_cannot_expand_resource_group(client):
    path = (
        f"/subscriptions/{SUB}/resourcegroups/ephemeral/providers/microsoft.compute/virtualmachines"
    )
    responses.get(ARM + path, json={"nextLink": ARM + path.replace("ephemeral", "production")})
    with pytest.raises(APIError):
        list(client.pages("compute", path))


@responses.activate
def test_repeated_pagination_token_stops_discovery(client):
    path = f"/subscriptions/{SUB}/resources"
    responses.get(ARM + path, json={"nextLink": ARM + path})
    with pytest.raises(APIError):
        list(client.pages("resources", path))
    assert len(responses.calls) == 2


@responses.activate
def test_mutation_is_not_retried(client):
    path = (
        f"/subscriptions/{SUB}/resourcegroups/ephemeral/providers"
        "/microsoft.compute/virtualmachines/vm/deallocate"
    )
    responses.post(ARM + path, status=503)
    with pytest.raises(APIError):
        client.request("compute", path, "POST")
    assert len(responses.calls) == 1


@responses.activate
def test_redirects_are_not_followed(client):
    path = f"/subscriptions/{SUB}/resources"
    responses.get(ARM + path, status=302, headers={"Location": "https://attacker.invalid/"})
    with pytest.raises(APIError):
        client.get("resources", path)
    assert len(responses.calls) == 1


@responses.activate
def test_http_deadline_reached_before_token_or_request(client):
    client.check_time = lambda: (_ for _ in ()).throw(TimeoutError())
    with pytest.raises(TimeoutError):
        client.get("resources", f"/subscriptions/{SUB}/resources")
    assert not responses.calls


@pytest.mark.parametrize(
    "code,body,mode,outcome",
    [
        (200, {"status": "Succeeded"}, "status", "succeeded"),
        (200, {"status": "Running"}, "status", "pending"),
        (200, {"status": "Failed"}, "status", "failed"),
        (200, {"status": "Canceled"}, "status", "failed"),
        (202, {}, "location", "pending"),
        (200, {"properties": {}}, "location", "succeeded"),
        (204, None, "location", "succeeded"),
    ],
)
@responses.activate
def test_arm_long_running_operation_states(client, code, body, mode, outcome):
    url = f"{ARM}/subscriptions/{SUB}/providers/Microsoft.Compute/locations/eastus/operations/op"
    responses.get(url, status=code, json=body)
    assert client.poll({"kind": "compute", "url": url, "mode": mode}) == outcome


@responses.activate
def test_unknown_operation_response_is_not_success(client):
    url = f"{ARM}/subscriptions/{SUB}/operations/op"
    responses.get(url, json={})
    with pytest.raises(APIError):
        client.poll({"kind": "compute", "url": url, "mode": "status"})


def test_accepted_operation_requires_reconciliation_url(client):
    response = requests.Response()
    response.status_code = 202
    with pytest.raises(APIError):
        client.operation("compute", response, "vm")


def test_operation_rejects_foreign_polling_url(client):
    response = requests.Response()
    response.status_code = 202
    response.headers["Azure-AsyncOperation"] = "https://attacker.invalid/"
    with pytest.raises(ConfigError):
        client.operation("compute", response, "vm")


def test_operator_managed_identity_needs_explicit_client_id(policy):
    with pytest.raises(ConfigError):
        replace(policy, credential_mode="managed_identity")
