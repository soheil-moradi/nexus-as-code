"""
apt.py - Nexus 3 APT repository management
Supports: hosted, proxy (no group)
"""

import logging
logger = logging.getLogger(__name__)

FORMAT = "apt"

def create_repository(session, base_url: str, repo: dict) -> bool:
    repo_type = repo.get("type", "").lower()
    handlers = {
        "hosted": _create_hosted,
        "proxy":  _create_proxy,
    }
    handler = handlers.get(repo_type)
    if not handler:
        logger.error(f"APT: unsupported type '{repo_type}' for '{repo.get('name')}'")
        return False
    return handler(session, base_url, repo)

def _repo_exists(session, base_url: str, name: str) -> bool:
    url = f"{base_url}/service/rest/v1/repositories"
    resp = session.get(url)
    resp.raise_for_status()
    return any(r.get("name") == name for r in resp.json())

def _create_hosted(session, base_url: str, repo: dict) -> bool:
    name = repo["name"]
    if _repo_exists(session, base_url, name):
        logger.info(f"APT hosted repo '{name}' already exists – skipping.")
        return True
    url = f"{base_url}/service/rest/v1/repositories/apt/hosted"
    payload = {
        "name": name,
        "online": repo.get("online", True),
        "storage": {
            "blobStoreName": repo.get("blob_store", "default"),
            "strictContentTypeValidation": repo.get("strict_content", True),
            "writePolicy": repo.get("write_policy", "allow_once"),
        },
        "apt": {
            "distribution": repo.get("distribution", "bionic"),
        },
        "aptSigning": {
            "keypair": repo.get("signing_keypair", ""),
            "passphrase": repo.get("signing_passphrase", ""),
        },
    }
    resp = session.post(url, json=payload)
    if resp.status_code in (200, 201, 204):
        logger.info(f"Created APT hosted repo '{name}'.")
        return True
    logger.error(f"Failed: {resp.status_code} {resp.text}")
    return False

def _create_proxy(session, base_url: str, repo: dict) -> bool:
    name = repo["name"]
    if _repo_exists(session, base_url, name):
        logger.info(f"APT proxy repo '{name}' already exists – skipping.")
        return True
    url = f"{base_url}/service/rest/v1/repositories/apt/proxy"
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
        "apt": {
            "distribution": repo.get("distribution", "bionic"),
            "flat": repo.get("flat", False),
        },
    }
    resp = session.post(url, json=payload)
    if resp.status_code in (200, 201, 204):
        logger.info(f"Created APT proxy repo '{name}'.")
        return True
    logger.error(f"Failed: {resp.status_code} {resp.text}")
    return False