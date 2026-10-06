"""Azure Blob Storage conditional reads/writes; SDK retries are disabled."""

import json

from azure.core import MatchConditions
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient, ContentSettings


class BlobObjects:
    def __init__(self, container):
        self.container = container

    @classmethod
    def connect(cls, policy, credential):
        service = BlobServiceClient(
            account_url=policy.blob_url,
            credential=credential,
            retry_total=0,
            connection_timeout=3,
            read_timeout=10,
        )
        return cls(service.get_container_client(policy.state_container))

    def read(self, key):
        blob = self.container.get_blob_client(key)
        try:
            props = blob.get_blob_properties(timeout=10)
        except ResourceNotFoundError:
            return None, 0
        body = blob.download_blob(
            etag=props.etag, match_condition=MatchConditions.IfNotModified, timeout=10
        ).readall()
        return json.loads(body), props.etag

    def write(self, key, body, generation):
        blob = self.container.get_blob_client(key)
        options = (
            {
                "etag": generation,
                "match_condition": MatchConditions.IfNotModified,
                "overwrite": True,
            }
            if generation
            else {"overwrite": False}
        )
        result = blob.upload_blob(
            json.dumps(body, sort_keys=True, allow_nan=False),
            content_settings=ContentSettings(content_type="application/json"),
            timeout=10,
            **options,
        )
        return result["etag"]

    def delete(self, key, generation):
        self.container.get_blob_client(key).delete_blob(
            etag=generation, match_condition=MatchConditions.IfNotModified, timeout=10
        )
