"""Stable eligibility fingerprints exclude secrets and transient API details."""

import hashlib
import json


def tags(raw):
    result = {}
    for key, value in (raw or {}).items():
        lowered = key.lower()
        if lowered in result:
            raise ValueError("Ambiguous tag names after case folding")
        result[lowered] = value
    return result


def fingerprint(resource, stop_authority=False):
    value = {
        k: resource[k] for k in ("id", "identity", "labels", "snapshot", "protection", "status")
    }
    if stop_authority:
        value["snapshot"] = {
            k: v
            for k, v in resource["snapshot"].items()
            if k not in ("power_state", "power_time", "provisioning_state", "etag")
        }
        value.pop("status")
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
