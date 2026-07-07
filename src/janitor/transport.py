"""Fixed ARM host, explicit API versions and no automatic mutation retries."""

from urllib.parse import parse_qs, urlparse

import requests

from .config import ConfigError

ARM = "https://management.azure.com"
VERSIONS = {
    "compute": "2025-04-01",
    "aks": "2025-05-01",
    "container_apps": "2025-07-01",
    "app_services": "2024-04-01",
    "logic_apps": "2019-05-01",
    "resources": "2021-04-01",
    "subscription": "2022-12-01",
    "locks": "2016-09-01",
    "storage": "2023-05-01",
}


class APIError(RuntimeError):
    def __init__(self, status, message="ARM API request failed"):
        self.status = status
        super().__init__(message)


class ARMClient:
    def __init__(self, policy, credential, session=None):
        self.policy = policy
        self.credential = credential
        self.session = session or requests.Session()
        self.check_time = lambda: None

    def validate_url(self, url):
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "management.azure.com"
            or parsed.fragment
            or "%" in parsed.path
            or any(p in (".", "..") for p in parsed.path.split("/"))
            or not (
                parsed.path.lower() == self.policy.subscription_prefix
                or parsed.path.lower().startswith(self.policy.subscription_prefix + "/")
            )
        ):
            raise ConfigError("ARM URL escaped the configured subscription/host")
        return parsed

    def request(self, kind, path, method="GET", body=None, headers=None):
        self.check_time()
        url = path if path.startswith("https://") else ARM + path
        parsed = self.validate_url(url)
        params = (
            None if "api-version" in parse_qs(parsed.query) else {"api-version": VERSIONS[kind]}
        )
        token = self.credential.get_token("https://management.azure.com/.default")
        response = self.session.request(
            method,
            url,
            params=params,
            json=body,
            headers={
                "Authorization": "Bearer " + token.token,
                "Accept": "application/json",
                **(headers or {}),
            },
            timeout=(3, 10),
            allow_redirects=False,
        )
        if not 200 <= response.status_code < 300:
            raise APIError(response.status_code)
        return response

    def get(self, kind, path):
        return self.request(kind, path).json()

    def pages(self, kind, path):
        seen = set()
        original = self.validate_url(ARM + path).path.lower()
        while path:
            page = self.get(kind, path)
            if not isinstance(page.get("value", []), list):
                raise APIError(502, "Invalid discovery response")
            yield from page.get("value", [])
            path = page.get("nextLink")
            if path:
                parsed = self.validate_url(path)
                if parsed.path.lower() != original or path in seen:
                    raise APIError(502, "Invalid pagination scope or cycle")
                seen.add(path)

    def operation(self, kind, response, name):
        url = response.headers.get("Azure-AsyncOperation") or response.headers.get(
            "Operation-Location"
        )
        mode = "status"
        if not url:
            url, mode = response.headers.get("Location"), "location"
        if response.status_code == 202 and not url:
            raise APIError(502, "Accepted action has no reconciliation URL")
        if url:
            self.validate_url(url)
        return {"kind": kind, "url": url, "mode": mode, "resource_id": name}

    def poll(self, operation):
        if not operation.get("url"):
            return (
                "succeeded"  # ARM returned synchronous success; eligibility still requires refresh.
            )
        response = self.request(operation["kind"], operation["url"])
        body = response.json() if response.content else {}
        status = str(body.get("status", "")).lower()
        if body.get("error") or status in ("failed", "canceled", "cancelled"):
            return "failed"
        if status == "succeeded":
            return "succeeded"
        if operation["mode"] == "location" and response.status_code in (200, 204) and not status:
            return "succeeded"
        if response.status_code == 202 or status in (
            "running",
            "inprogress",
            "accepted",
            "updating",
        ):
            return "pending"
        raise APIError(502, "Unrecognized operation response; manual reconciliation required")
