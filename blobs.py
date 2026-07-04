"""
blobs.py - Nexus 3 Blob Store management
Supports: file, s3 (Amazon AWS), s3 (self-hosted MinIO)
"""

import logging
logger = logging.getLogger(__name__)

def create_blob_store(session, base_url: str, blob: dict) -> bool:
    blob_type = blob.get("type", "file").lower()
    if blob_type == "file":
        return _create_file_blob(session, base_url, blob)
    elif blob_type == "s3":
        provider = blob.get("s3_provider", "aws").lower()
        if provider == "minio":
            return _create_minio_blob(session, base_url, blob)
        return _create_aws_s3_blob(session, base_url, blob)
    else:
        logger.error(f"Unsupported blob type '{blob_type}' for blob '{blob.get('name')}'")
        return False

def _blob_exists(session, base_url: str, name: str) -> bool:
    url = f"{base_url}/service/rest/v1/blobstores"
    resp = session.get(url)
    resp.raise_for_status()
    return any(b.get("name") == name for b in resp.json())

def _create_file_blob(session, base_url: str, blob: dict) -> bool:
    name = blob["name"]
    if _blob_exists(session, base_url, name):
        logger.info(f"Blob store '{name}' already exists – skipping.")
        return True
    url = f"{base_url}/service/rest/v1/blobstores/file"
    payload = {
        "name": name,
        "path": blob.get("path", f"/nexus-data/blobs/{name}"),
    }
    resp = session.post(url, json=payload)
    if resp.status_code in (200, 201, 204):
        logger.info(f"Created file blob store '{name}'.")
        return True
    logger.error(f"Failed to create file blob store '{name}': {resp.status_code} {resp.text}")
    return False

def _create_aws_s3_blob(session, base_url: str, blob: dict) -> bool:
    name = blob["name"]
    if _blob_exists(session, base_url, name):
        logger.info(f"AWS S3 blob store '{name}' already exists – skipping.")
        return True
    bucket_security = {
        "accessKeyId":     blob.get("access_key_id", ""),
        "secretAccessKey": blob.get("secret_access_key", ""),
    }
    if blob.get("session_token"):
        bucket_security["sessionToken"] = blob["session_token"]
    if blob.get("assume_role"):
        bucket_security["role"] = blob["assume_role"]

    encryption = blob.get("encryption", "none")
    encryption_cfg = {}
    if encryption == "s3ManagedEncryption":
        encryption_cfg = {"encryptionType": "s3ManagedEncryption"}
    elif encryption == "kmsManagedEncryption":
        encryption_cfg = {
            "encryptionType": "kmsManagedEncryption",
            "encryptionKey":  blob.get("kms_key_id", ""),
        }

    payload = {
        "name": name,
        "bucketConfiguration": {
            "bucket": {
                "region":     blob.get("region", "us-east-1"),
                "name":       blob["bucket"],
                "prefix":     blob.get("prefix", ""),
                "expiration": blob.get("expiration", 3),
            },
            "bucketSecurity": bucket_security,
        },
    }
    if encryption_cfg:
        payload["bucketConfiguration"]["encryption"] = encryption_cfg

    url = f"{base_url}/service/rest/v1/blobstores/s3"
    resp = session.post(url, json=payload)
    if resp.status_code in (200, 201, 204):
        logger.info(f"Created AWS S3 blob store '{name}'.")
        return True
    logger.error(f"Failed to create AWS S3 blob store '{name}': {resp.status_code} {resp.text}")
    return False

def _create_minio_blob(session, base_url: str, blob: dict) -> bool:
    name = blob["name"]
    if _blob_exists(session, base_url, name):
        logger.info(f"MinIO blob store '{name}' already exists – skipping.")
        return True
    endpoint = blob.get("endpoint", "")
    if not endpoint:
        logger.error(f"MinIO blob store '{name}' is missing the required 'endpoint' key.")
        return False
    payload = {
        "name": name,
        "bucketConfiguration": {
            "bucket": {
                "region":     blob.get("region", "us-east-1"),
                "name":       blob["bucket"],
                "prefix":     blob.get("prefix", ""),
                "expiration": blob.get("expiration", 3),
            },
            "bucketSecurity": {
                "accessKeyId":     blob.get("access_key_id", ""),
                "secretAccessKey": blob.get("secret_access_key", ""),
            },
            "advancedBucketConnection": {
                "endpoint":       endpoint,
                "forcePathStyle": blob.get("force_path_style", True),
                "signerType":     blob.get("signer_type", "Default"),
            },
        },
    }
    url = f"{base_url}/service/rest/v1/blobstores/s3"
    resp = session.post(url, json=payload)
    if resp.status_code in (200, 201, 204):
        logger.info(f"Created MinIO blob store '{name}' (endpoint: {endpoint}).")
        return True
    logger.error(f"Failed to create MinIO blob store '{name}': {resp.status_code} {resp.text}")
    return False