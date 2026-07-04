"""
docker.py - Nexus 3 Docker repository management
Supports: hosted, proxy, group
"""

import logging
logger = logging.getLogger(__name__)

FORMAT = "docker"

def create_repository(session, base_url: str, repo: dict) -> bool:
    repo_type = repo.get("type", "").lower()
    handlers = {
        "hosted": _create_hosted,
        "proxy":  _create_proxy,
        "group":  _create_group,
    }
    handler = handlers.get(repo_type)
    if not handler:
        logger.error(f"Docker: unsupported type '{repo_type}' for '{repo.get('name')}'")
        return False
    return handler(session, base_url, repo)

def _repo_exists(session, base_url: str, name: str) -> bool:
    url = f"{base_url}/service/rest/v1/repositories"
    resp = session.get(url)
    resp.raise_for_status()
    return any(r.get("name") == name for r in resp.json())

def _docker_section(repo: dict, repo_type: str = None) -> dict:
    connector = repo.get("connector", "path").lower()
    section = {
        "v1Enabled":      repo.get("v1_enabled", False),
        "forceBasicAuth": repo.get("force_basic_auth", True),
    }

    # Groups only support path-based routing.
    if repo_type == "group":
        section["subdomain"] = None
        return section

    if connector == "port":
        if repo.get("http_port"):
            section["httpPort"] = int(repo["http_port"])
        if repo.get("https_port"):
            section["httpsPort"] = int(repo["https_port"])
    else:  # connector == "path"
       # Explicitly sending the subdomain with a value of None to enable path-based routing
        section["subdomain"] = None

    return section

def _create_hosted(session, base_url: str, repo: dict) -> bool:
    name = repo["name"]
    if _repo_exists(session, base_url, name):
        logger.info(f"Docker hosted repo '{name}' already exists – skipping.")
        return True
    url = f"{base_url}/service/rest/v1/repositories/docker/hosted"
    payload = {
        "name": name,
        "online": repo.get("online", True),
        "storage": {
            "blobStoreName": repo.get("blob_store", "default"),
            "strictContentTypeValidation": repo.get("strict_content", True),
            "writePolicy": repo.get("write_policy", "allow"),
        },
        "docker": _docker_section(repo, "hosted"),
    }
    resp = session.post(url, json=payload)
    if resp.status_code in (200, 201, 204):
        logger.info(f"Created Docker hosted repo '{name}'.")
        return True
    logger.error(f"Failed: {resp.status_code} {resp.text}")
    return False

def _create_proxy(session, base_url: str, repo: dict) -> bool:
    name = repo["name"]
    if _repo_exists(session, base_url, name):
        logger.info(f"Docker proxy repo '{name}' already exists – skipping.")
        return True
    url = f"{base_url}/service/rest/v1/repositories/docker/proxy"
    remote_url = repo["remote_url"]
    index_type = repo.get("index_type", "REGISTRY").upper()
    if index_type == "HUB" or "docker.io" in remote_url:
        index_type = "HUB"
    docker_proxy = {
        "indexType": index_type,
        "cacheForeignLayers": repo.get("foreign_layers", True),
    }
    if index_type == "HUB":
        docker_proxy["indexUrl"] = "https://index.docker.io/"
    payload = {
        "name": name,
        "online": repo.get("online", True),
        "storage": {
            "blobStoreName": repo.get("blob_store", "default"),
            "strictContentTypeValidation": repo.get("strict_content", True),
        },
        "proxy": {
            "remoteUrl": remote_url,
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
        "docker": _docker_section(repo, "proxy"),
        "dockerProxy": docker_proxy,
    }
    resp = session.post(url, json=payload)
    if resp.status_code in (200, 201, 204):
        logger.info(f"Created Docker proxy repo '{name}'.")
        return True
    logger.error(f"Failed: {resp.status_code} {resp.text}")
    return False

def _create_group(session, base_url: str, repo: dict) -> bool:
    name = repo["name"]
    if _repo_exists(session, base_url, name):
        logger.info(f"Docker group repo '{name}' already exists – skipping.")
        return True
    url = f"{base_url}/service/rest/v1/repositories/docker/group"
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
        "docker": _docker_section(repo, "group"),
    }
    resp = session.post(url, json=payload)
    if resp.status_code in (200, 201, 204):
        logger.info(f"Created Docker group repo '{name}'.")
        return True
    logger.error(f"Failed: {resp.status_code} {resp.text}")
    return False