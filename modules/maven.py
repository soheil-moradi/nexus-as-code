"""
maven.py - Nexus 3 Maven repository management
Supports: hosted, proxy, group
"""

import logging
logger = logging.getLogger(__name__)

FORMAT = "maven2"
VALID_VERSION_POLICIES = {"release", "snapshot", "mixed"}
VALID_LAYOUT_POLICIES = {"strict", "permissive"}
VALID_CONTENT_DISPOSITIONS = {"inline", "attachment"}

def create_repository(session, base_url: str, repo: dict) -> bool:
    repo_type = repo.get("type", "").lower()
    handlers = {
        "hosted": _create_hosted,
        "proxy":  _create_proxy,
        "group":  _create_group,
    }
    handler = handlers.get(repo_type)
    if not handler:
        logger.error(f"Maven: unsupported type '{repo_type}' for '{repo.get('name')}'")
        return False
    return handler(session, base_url, repo)

def _repo_exists(session, base_url: str, name: str) -> bool:
    url = f"{base_url}/service/rest/v1/repositories"
    resp = session.get(url)
    resp.raise_for_status()
    return any(r.get("name") == name for r in resp.json())

def _maven_section(repo: dict, default_version: str = "release") -> dict:
    version_policy = repo.get("version_policy", default_version).lower()
    layout_policy = repo.get("layout_policy", "strict").lower()
    content_disposition = repo.get("content_disposition", "inline").lower()
    if version_policy not in VALID_VERSION_POLICIES:
        version_policy = "release"
    if layout_policy not in VALID_LAYOUT_POLICIES:
        layout_policy = "strict"
    if content_disposition not in VALID_CONTENT_DISPOSITIONS:
        content_disposition = "inline"
    return {
        "versionPolicy": version_policy.upper(),
        "layoutPolicy": layout_policy.upper(),
        "contentDisposition": content_disposition.upper(),
    }

def _create_hosted(session, base_url: str, repo: dict) -> bool:
    name = repo["name"]
    if _repo_exists(session, base_url, name):
        logger.info(f"Maven hosted repo '{name}' already exists – skipping.")
        return True
    url = f"{base_url}/service/rest/v1/repositories/maven/hosted"
    payload = {
        "name": name,
        "online": repo.get("online", True),
        "storage": {
            "blobStoreName": repo.get("blob_store", "default"),
            "strictContentTypeValidation": repo.get("strict_content", True),
            "writePolicy": repo.get("write_policy", "allow_once"),
        },
        "maven": _maven_section(repo),
    }
    resp = session.post(url, json=payload)
    if resp.status_code in (200, 201, 204):
        logger.info(f"Created Maven hosted repo '{name}'.")
        return True
    logger.error(f"Failed: {resp.status_code} {resp.text}")
    return False

def _create_proxy(session, base_url: str, repo: dict) -> bool:
    name = repo["name"]
    if _repo_exists(session, base_url, name):
        logger.info(f"Maven proxy repo '{name}' already exists – skipping.")
        return True
    url = f"{base_url}/service/rest/v1/repositories/maven/proxy"
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
        "maven": _maven_section(repo),
    }
    resp = session.post(url, json=payload)
    if resp.status_code in (200, 201, 204):
        logger.info(f"Created Maven proxy repo '{name}'.")
        return True
    logger.error(f"Failed: {resp.status_code} {resp.text}")
    return False

def _create_group(session, base_url: str, repo: dict) -> bool:
    name = repo["name"]
    if _repo_exists(session, base_url, name):
        logger.info(f"Maven group repo '{name}' already exists – skipping.")
        return True
    url = f"{base_url}/service/rest/v1/repositories/maven/group"
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
        "maven": _maven_section(repo, default_version="mixed"),
    }
    resp = session.post(url, json=payload)
    if resp.status_code in (200, 201, 204):
        logger.info(f"Created Maven group repo '{name}'.")
        return True
    logger.error(f"Failed: {resp.status_code} {resp.text}")
    return False