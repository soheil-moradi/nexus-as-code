"""
helm.py - Nexus 3 Helm repository management
Supports: hosted, proxy, group
"""

import logging
logger = logging.getLogger(__name__)

FORMAT = "helm"

def create_repository(session, base_url: str, repo: dict) -> bool:
    repo_type = repo.get("type", "").lower()
    handlers = {
        "hosted": _create_hosted,
        "proxy":  _create_proxy,
        "group":  _create_group,
    }
    handler = handlers.get(repo_type)
    if not handler:
        logger.error(f"Helm: unsupported type '{repo_type}' for '{repo.get('name')}'")
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
        logger.info(f"Helm hosted repo '{name}' already exists – skipping.")
        return True
    url = f"{base_url}/service/rest/v1/repositories/helm/hosted"
    payload = {
        "name": name,
        "online": repo.get("online", True),
        "storage": {
            "blobStoreName": repo.get("blob_store", "default"),
            "strictContentTypeValidation": repo.get("strict_content", True),
            "writePolicy": repo.get("write_policy", "allow_once"),
        },
    }
    resp = session.post(url, json=payload)
    if resp.status_code in (200, 201, 204):
        logger.info(f"Created Helm hosted repo '{name}'.")
        return True
    logger.error(f"Failed: {resp.status_code} {resp.text}")
    return False

def _create_proxy(session, base_url: str, repo: dict) -> bool:
    name = repo["name"]
    if _repo_exists(session, base_url, name):
        logger.info(f"Helm proxy repo '{name}' already exists – skipping.")
        return True
    url = f"{base_url}/service/rest/v1/repositories/helm/proxy"
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
    }
    resp = session.post(url, json=payload)
    if resp.status_code in (200, 201, 204):
        logger.info(f"Created Helm proxy repo '{name}'.")
        return True
    logger.error(f"Failed: {resp.status_code} {resp.text}")
    return False

def _create_group(session, base_url: str, repo: dict) -> bool:
    name = repo["name"]
    if _repo_exists(session, base_url, name):
        logger.info(f"Helm group repo '{name}' already exists – skipping.")
        return True
    url = f"{base_url}/service/rest/v1/repositories/helm/group"
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
    }
    resp = session.post(url, json=payload)
    if resp.status_code in (200, 201, 204):
        logger.info(f"Created Helm group repo '{name}'.")
        return True
    logger.error(f"Failed: {resp.status_code} {resp.text}")
    return False