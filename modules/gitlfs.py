"""
gitlfs.py - Nexus 3 Git LFS repository management
Supports: hosted only (as per Nexus API)
"""

import logging
logger = logging.getLogger(__name__)

FORMAT = "gitlfs"

def create_repository(session, base_url: str, repo: dict) -> bool:
    repo_type = repo.get("type", "").lower()
    if repo_type == "hosted":
        return _create_hosted(session, base_url, repo)
    logger.error(f"Git LFS: unsupported type '{repo_type}' for '{repo.get('name')}' (only 'hosted' is supported)")
    return False

def _repo_exists(session, base_url: str, name: str) -> bool:
    url = f"{base_url}/service/rest/v1/repositories"
    resp = session.get(url)
    resp.raise_for_status()
    return any(r.get("name") == name for r in resp.json())

def _create_hosted(session, base_url: str, repo: dict) -> bool:
    name = repo["name"]
    if _repo_exists(session, base_url, name):
        logger.info(f"Git LFS hosted repo '{name}' already exists – skipping.")
        return True
    url = f"{base_url}/service/rest/v1/repositories/{FORMAT}/hosted"
    payload = {
        "name": name,
        "online": repo.get("online", True),
        "storage": {
            "blobStoreName": repo.get("blob_store", "default"),
            "strictContentTypeValidation": repo.get("strict_content", True),
            "writePolicy": repo.get("write_policy", "allow_once"),
        },
        "component": {
            "proprietaryComponents": repo.get("proprietary_components", True),
        },
    }
    resp = session.post(url, json=payload)
    if resp.status_code in (200, 201, 204):
        logger.info(f"Created Git LFS hosted repo '{name}'.")
        return True
    logger.error(f"Failed: {resp.status_code}")
    return False