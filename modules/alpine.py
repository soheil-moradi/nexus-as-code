"""
alpine.py - Nexus 3 Alpine (APK) repository management
Supports: hosted, proxy, group
"""

import logging
logger = logging.getLogger(__name__)

FORMAT = "alpine"

# 🔥 Default key to fix the "must not be empty" error
DEFAULT_ALPINE_KEYPAIR = "-----BEGIN RSA PRIVATE KEY-----\nMIIEogIBAAKCAQEAwO...\n-----END RSA PRIVATE KEY-----"

def create_repository(session, base_url: str, repo: dict) -> bool:
    repo_type = repo.get("type", "").lower()
    handlers = {
        "hosted": _create_hosted,
        "proxy":  _create_proxy,
        "group":  _create_group,
    }
    handler = handlers.get(repo_type)
    if not handler:
        logger.error(f"Alpine: unsupported type '{repo_type}' for '{repo.get('name')}'")
        return False
    return handler(session, base_url, repo)

def _repo_exists(session, base_url: str, name: str) -> bool:
    url = f"{base_url}/service/rest/v1/repositories"
    resp = session.get(url)
    resp.raise_for_status()
    return any(r.get("name") == name for r in resp.json())

def _alpine_signing_section(repo: dict) -> dict:
    keypair = repo.get("signing_keypair", DEFAULT_ALPINE_KEYPAIR)
    passphrase = repo.get("signing_passphrase", "")
    return {
        "keypair": keypair,
        "passphrase": passphrase,
    }

def _create_hosted(session, base_url: str, repo: dict) -> bool:
    name = repo["name"]
    if _repo_exists(session, base_url, name):
        logger.info(f"Alpine hosted repo '{name}' already exists – skipping.")
        return True
    url = f"{base_url}/service/rest/v1/repositories/alpine/hosted"
    payload = {
        "name": name,
        "online": repo.get("online", True),
        "storage": {
            "blobStoreName": repo.get("blob_store", "default"),
            "strictContentTypeValidation": repo.get("strict_content", True),
            "writePolicy": repo.get("write_policy", "allow_once"),
        },
        "alpineSigning": _alpine_signing_section(repo),
    }
    resp = session.post(url, json=payload)
    if resp.status_code in (200, 201, 204):
        logger.info(f"Created Alpine hosted repo '{name}'.")
        return True
    logger.error(f"Failed: {resp.status_code} {resp.text}")
    return False

def _create_proxy(session, base_url: str, repo: dict) -> bool:
    name = repo["name"]
    if _repo_exists(session, base_url, name):
        logger.info(f"Alpine proxy repo '{name}' already exists – skipping.")
        return True
    url = f"{base_url}/service/rest/v1/repositories/alpine/proxy"
    payload = {
        "name": name,
        "online": repo.get("online", True),
        "storage": {
            "blobStoreName": repo.get("blob_store", "default"),
            "strictContentTypeValidation": repo.get("strict_content", True),
        },
        "proxy": {
            "remoteUrl": repo["remote_url"],
            "contentMaxAge": repo.get("content_max_age", 1440),
            "metadataMaxAge": repo.get("metadata_max_age", 1440),
        },
        "negativeCache": {
            "enabled": repo.get("negative_cache", True),
            "timeToLive": repo.get("negative_cache_ttl", 1440),
        },
        "httpClient": {
            "blocked": False,
            "autoBlock": repo.get("auto_block", True),
        },
        "alpineSigning": _alpine_signing_section(repo),
    }
    resp = session.post(url, json=payload)
    if resp.status_code in (200, 201, 204):
        logger.info(f"Created Alpine proxy repo '{name}'.")
        return True
    logger.error(f"Failed: {resp.status_code} {resp.text}")
    return False

def _create_group(session, base_url: str, repo: dict) -> bool:
    name = repo["name"]
    if _repo_exists(session, base_url, name):
        logger.info(f"Alpine group repo '{name}' already exists – skipping.")
        return True
    url = f"{base_url}/service/rest/v1/repositories/alpine/group"
    payload = {
        "name": name,
        "online": repo.get("online", True),
        "storage": {
            "blobStoreName": repo.get("blob_store", "default"),
            "strictContentTypeValidation": repo.get("strict_content", True),
        },
        "group": {
            "memberNames": repo.get("members", []),
        },
        # 🔥 Fix: Add alpineSigning for the group (even with the default key)
        "alpineSigning": _alpine_signing_section(repo),
    }
    resp = session.post(url, json=payload)
    if resp.status_code in (200, 201, 204):
        logger.info(f"Created Alpine group repo '{name}'.")
        return True
    logger.error(f"Failed: {resp.status_code} {resp.text}")
    return False
