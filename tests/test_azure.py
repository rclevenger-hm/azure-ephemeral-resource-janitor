import json

import pytest
import responses
from conftest import Credential, cluster, pool, vm

from janitor.azure import Azure
from janitor.resources import normalize
from janitor.transport import ARM


@pytest.mark.parametrize(
    "action,verb,suffix", [("deallocate", "POST", "/deallocate"), ("delete", "DELETE", "")]
)
@responses.activate
def test_vm_actions_never_force_or_claim_conditional_mutation(policy, action, verb, suffix):
    raw = vm()
    resource = normalize(policy, "compute", raw["id"], raw)
    responses.add(verb, ARM + raw["id"] + suffix, status=204)
    result = Azure(policy, Credential()).act(resource, action, "correlation-uuid")
    request = responses.calls[0].request
    assert request.headers["x-ms-client-request-id"] == "correlation-uuid"
    assert "If-Match" not in request.headers
    assert "force" not in request.url and not request.body
    assert result["url"] is None and result["kind"] == "compute"


@responses.activate
def test_pool_stop_uses_etag_and_preserves_capacity(policy):
    raw = pool()
    resource = normalize(policy, "aks", raw["id"], raw, cluster=cluster())
    responses.put(ARM + raw["id"], status=200, json={})
    Azure(policy, Credential()).act(resource, "stop_pool", "correlation-uuid")
    request = responses.calls[0].request
    assert request.headers["If-Match"] == '"pool-etag"'
    assert json.loads(request.body) == {"properties": {"powerState": {"code": "Stopped"}}}
