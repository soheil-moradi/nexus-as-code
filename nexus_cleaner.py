#!/usr/bin/env python3
"""Conservative, explicitly scoped deletion of managed Nexus resources.

This tool intentionally does not provide 'delete all' or wildcard actions.
Plan mode is the default. Deletion always requires explicit names and a
confirmation of the exact Nexus URL.
"""

import argparse
import logging
import sys
from urllib.parse import quote

import requests

from config_secrets import resolve_environment_references
from config_validation import validate_config
from main import (
    FORMAT_MODULE_MAP,
    build_session,
    configure_log_redaction,
    load_config_from_dir,
    resolve_nexus_credentials,
    verify_connection,
)

logger = logging.getLogger("cleaner")


class CleanupError(Exception):
    """Safety check or API operation failed; never continue deleting."""


def _get_list(session, url):
    response = session.get(url)
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, list):
        raise CleanupError("Unexpected Nexus inventory response; aborting")
    return result


def plan_cleanup(session, base_url, config, repositories, blobstores):
    """Return a safe plan; verify target names and any surviving blob users."""
    configured_repositories = {
        repo["name"] for items in config.get("repositories", {}).values() for repo in items
    }
    configured_blobs = {blob["name"] for blob in config.get("blobs", [])}
    if not repositories and not blobstores:
        raise CleanupError("Provide at least one --repository or --blobstore; no wildcards allowed")
    if not set(repositories) <= configured_repositories:
        raise CleanupError("Every selected repository must be defined in local configuration")
    if "default" in blobstores:
        raise CleanupError("The default blob store cannot be deleted")
    if not set(blobstores) <= configured_blobs:
        raise CleanupError("Every selected blob store must be defined in local configuration")
    if len(repositories) != len(set(repositories)) or len(blobstores) != len(set(blobstores)):
        raise CleanupError("Duplicate resource selection is not permitted")

    remote_repos = _get_list(session, f"{base_url}/service/rest/v1/repositories")
    remote_blobs = _get_list(session, f"{base_url}/service/rest/v1/blobstores")
    repo_map = {item["name"]: item for item in remote_repos}
    blob_names = {item["name"] for item in remote_blobs}
    if any(name not in repo_map for name in repositories):
        raise CleanupError("A selected repository does not exist on the target Nexus")
    if any(name not in blob_names for name in blobstores):
        raise CleanupError("A selected blob store does not exist on the target Nexus")

    if repositories or blobstores:
        # REST inventory does not expose all group memberships / blob mappings.
        # Inspect surviving groups before deletion so we cannot silently remove
        # members still consumed by another group.
        for repo in remote_repos:
            if repo["name"] in repositories or repo.get("type") != "group":
                continue
            fmt, kind, name = repo.get("format"), repo.get("type"), repo["name"]
            if not fmt or not kind:
                raise CleanupError(f"Cannot inspect group dependencies for '{name}'")
            detail_url = (f"{base_url}/service/rest/v1/repositories/"
                          f"{quote(fmt, safe='')}/{quote(kind, safe='')}/{quote(name, safe='')}")
            detail_response = session.get(detail_url)
            detail_response.raise_for_status()
            detail = detail_response.json()
            group = detail.get("group") if isinstance(detail, dict) else None
            if not isinstance(group, dict) or not isinstance(group.get("memberNames"), list):
                raise CleanupError(f"Cannot inspect surviving group '{name}'")
            if set(group["memberNames"]) & set(repositories):
                raise CleanupError(f"Repository is still used by surviving group '{name}'")

    if blobstores:
        # REST inventory does not expose all blob store mappings. Inspect the
        # detailed configuration of every surviving repo; fail closed on any
        # uninspectable repository rather than risk destroying in-use storage.
        for repo in remote_repos:
            if repo["name"] in repositories:
                continue
            fmt, kind, name = repo.get("format"), repo.get("type"), repo["name"]
            if not fmt or not kind:
                raise CleanupError(f"Cannot inspect blob dependencies for '{name}'")
            url = (f"{base_url}/service/rest/v1/repositories/"
                   f"{quote(fmt, safe='')}/{quote(kind, safe='')}/{quote(name, safe='')}")
            response = session.get(url)
            response.raise_for_status()
            detail = response.json()
            if not isinstance(detail, dict):
                raise CleanupError(f"Unexpected repository details for '{name}'")
            storage = detail.get("storage")
            if not isinstance(storage, dict) or not isinstance(storage.get("blobStoreName"), str):
                raise CleanupError(f"Cannot verify blob store for surviving repository '{name}'")
            if storage["blobStoreName"] in blobstores:
                raise CleanupError(f"Blob store is still used by surviving repository '{name}'")
    # Groups must be removed before their members to avoid dependency errors.
    ordered_repositories = sorted(repositories, key=lambda name: repo_map[name].get("type") != "group")
    return ordered_repositories, list(blobstores)


def execute_cleanup(session, base_url, repositories, blobstores):
    """Delete explicitly selected repos first, then blob stores; stop on errors."""
    for name in repositories:
        response = session.delete(f"{base_url}/service/rest/v1/repositories/{quote(name, safe='')}")
        response.raise_for_status()
        logger.info("Deleted repository '%s'", name)
    for name in blobstores:
        response = session.delete(f"{base_url}/service/rest/v1/blobstores/{quote(name, safe='')}")
        response.raise_for_status()
        logger.info("Deleted blob store '%s'", name)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Safely remove explicitly selected Nexus resources")
    parser.add_argument("--config-dir", default="config.d")
    parser.add_argument("--repository", action="append", default=[], help="Exact configured repository name")
    parser.add_argument("--blobstore", action="append", default=[], help="Exact configured blob store name")
    parser.add_argument("--apply", action="store_true", help="Actually delete the selected resources")
    parser.add_argument("--confirm-target", help="Required with --apply: exact Nexus base URL")
    args = parser.parse_args(argv)

    try:
        config = load_config_from_dir(args.config_dir)
        config, secrets = resolve_nexus_credentials(config)
        config, extra = resolve_environment_references(config)
        configure_log_redaction(secrets + extra)
        errors = validate_config(config, FORMAT_MODULE_MAP)
        if errors:
            raise CleanupError("Invalid configuration: " + "; ".join(errors))
        url = config["nexus"]["url"].rstrip("/")
        if args.apply and args.confirm_target != url:
            raise CleanupError("Deletion requires --confirm-target matching the exact Nexus URL")
        if not args.apply and args.confirm_target is not None:
            raise CleanupError("--confirm-target is only valid together with --apply")
        session = build_session(config["nexus"])
        if not verify_connection(session, url):
            raise CleanupError("Unable to verify Nexus connection")
        repos, blobs = plan_cleanup(session, url, config, args.repository, args.blobstore)
        for name in repos:
            logger.info("%s repository: %s", "DELETE" if args.apply else "PLAN", name)
        for name in blobs:
            logger.info("%s blob store: %s", "DELETE" if args.apply else "PLAN", name)
        if args.apply:
            execute_cleanup(session, url, repos, blobs)
        else:
            logger.info("Preview only; no deletions. To execute, add --apply --confirm-target '%s'", url)
        return 0
    except (CleanupError, ValueError, requests.RequestException) as exc:
        # Never print untrusted HTTP response bodies or secret values.
        if isinstance(exc, requests.RequestException):
            logger.error("Nexus API failed during cleanup; operation stopped")
        else:
            logger.error("Cleanup refused: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
