#!/usr/bin/env python3
"""Preview-first cleanup of selected, configured, or all Nexus resources.

Deleting resources is irreversible. Even in full mode, the default blob store is
protected. Every live deletion requires confirmation of the exact Nexus URL;
large-scale modes additionally require an explicit confirmation phrase.
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

CONFIRM_PHRASES = {"managed": "DELETE-MANAGED", "all": "DELETE-ALL"}


class CleanupError(Exception):
    """Safety check or API operation failed; never continue deleting."""


def _get_list(session, url, label):
    response = session.get(url)
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, list):
        raise CleanupError(f"Unexpected Nexus {label} inventory response; aborting")
    names = []
    for item in result:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"]:
            raise CleanupError(f"Invalid Nexus {label} inventory item; aborting")
        names.append(item["name"])
    if len(set(names)) != len(names):
        raise CleanupError(f"Duplicate names in Nexus {label} inventory; aborting")
    return result


def _group_members(session, base_url, repo):
    """Read the actual group memberships; never guess from local YAML."""
    fmt, kind, name = repo.get("format"), repo.get("type"), repo["name"]
    if not fmt or kind != "group":
        raise CleanupError(f"Cannot inspect group dependencies for '{name}'")
    detail_url = (f"{base_url}/service/rest/v1/repositories/"
                  f"{quote(fmt, safe='')}/group/{quote(name, safe='')}")
    response = session.get(detail_url)
    response.raise_for_status()
    detail = response.json()
    group = detail.get("group") if isinstance(detail, dict) else None
    members = group.get("memberNames") if isinstance(group, dict) else None
    if not isinstance(members, list) or any(not isinstance(m, str) or not m for m in members):
        raise CleanupError(f"Cannot inspect group members for '{name}'")
    return members


def _ordered_repositories(session, base_url, repo_map, repositories):
    """Delete parent groups before nested groups, then ordinary repositories."""
    selected_groups = [name for name in repositories if repo_map[name].get("type") == "group"]
    group_set = set(selected_groups)
    ordered_groups = []
    if len(selected_groups) > 1:
        # A simple group-first sort is insufficient for nested groups.
        children = {}
        incoming = {name: 0 for name in selected_groups}
        for name in selected_groups:
            members = _group_members(session, base_url, repo_map[name])
            children[name] = [member for member in members if member in group_set]
            for member in children[name]:
                incoming[member] += 1
        remaining = set(selected_groups)
        while remaining:
            ready = next((name for name in selected_groups
                          if name in remaining and incoming[name] == 0), None)
            if ready is None:
                raise CleanupError("Selected groups contain a dependency cycle; refusing deletion")
            ordered_groups.append(ready)
            remaining.remove(ready)
            for member in children[ready]:
                incoming[member] -= 1
    else:
        ordered_groups = selected_groups
    return ordered_groups + [name for name in repositories if name not in group_set]


def plan_cleanup(session, base_url, config, repositories, blobstores, *, mode="selective"):
    """Plan deletions using live Nexus inventory, without issuing DELETE calls.

    selective: explicitly named *configured* resources, all of which must exist.
    managed: configured resources that currently exist on Nexus.
    all: every remote repository and non-default blob store, configured or not.
    """
    if mode not in ("selective", "managed", "all"):
        raise CleanupError("Unsupported cleanup mode")
    if mode != "selective" and (repositories or blobstores):
        raise CleanupError("--managed/--all cannot be combined with named resources")
    if mode == "selective":
        configured_repositories = {
            repo["name"] for items in config.get("repositories", {}).values() for repo in items
        }
        configured_blobs = {blob["name"] for blob in config.get("blobs", [])}
        if not repositories and not blobstores:
            raise CleanupError("Provide --repository/--blobstore, --managed, or --all")
        if not set(repositories) <= configured_repositories:
            raise CleanupError("Every selected repository must be defined in local configuration")
        if "default" in blobstores:
            raise CleanupError("The default blob store cannot be deleted")
        if not set(blobstores) <= configured_blobs:
            raise CleanupError("Every selected blob store must be defined in local configuration")
        if len(repositories) != len(set(repositories)) or len(blobstores) != len(set(blobstores)):
            raise CleanupError("Duplicate resource selection is not permitted")

    remote_repos = _get_list(session, f"{base_url}/service/rest/v1/repositories", "repository")
    remote_blobs = _get_list(session, f"{base_url}/service/rest/v1/blobstores", "blob store")
    repo_map = {item["name"]: item for item in remote_repos}
    blob_names = {item["name"] for item in remote_blobs}

    if mode == "all":
        repositories = [item["name"] for item in remote_repos]
        blobstores = [item["name"] for item in remote_blobs if item["name"] != "default"]
    elif mode == "managed":
        configured_repositories = {
            repo["name"] for items in config.get("repositories", {}).values() for repo in items
        }
        configured_blobs = {blob["name"] for blob in config.get("blobs", [])}
        # Select only existing resources; a prior partial cleanup remains resumable.
        repositories = [item["name"] for item in remote_repos
                        if item["name"] in configured_repositories]
        blobstores = [item["name"] for item in remote_blobs
                      if item["name"] in configured_blobs and item["name"] != "default"]
    else:
        if any(name not in repo_map for name in repositories):
            raise CleanupError("A selected repository does not exist on the target Nexus")
        if any(name not in blob_names for name in blobstores):
            raise CleanupError("A selected blob store does not exist on the target Nexus")

    selected_repos = set(repositories)
    selected_blobs = set(blobstores)
    # Surviving groups must not still reference a repository selected for deletion.
    for repo in remote_repos:
        if repo["name"] in selected_repos or repo.get("type") != "group":
            continue
        if set(_group_members(session, base_url, repo)) & selected_repos:
            raise CleanupError(f"Repository is still used by surviving group '{repo['name']}'")

    if blobstores:
        # Even in managed mode, unconfigured repositories can use selected blobs.
        # Fail closed whenever a surviving repository cannot be inspected.
        for repo in remote_repos:
            if repo["name"] in selected_repos:
                continue
            fmt, kind, name = repo.get("format"), repo.get("type"), repo["name"]
            if not fmt or not kind:
                raise CleanupError(f"Cannot inspect blob dependencies for '{name}'")
            detail_url = (f"{base_url}/service/rest/v1/repositories/"
                          f"{quote(fmt, safe='')}/{quote(kind, safe='')}/{quote(name, safe='')}")
            response = session.get(detail_url)
            response.raise_for_status()
            detail = response.json()
            if not isinstance(detail, dict):
                raise CleanupError(f"Unexpected repository details for '{name}'")
            storage = detail.get("storage")
            if not isinstance(storage, dict) or not isinstance(storage.get("blobStoreName"), str):
                raise CleanupError(f"Cannot verify blob store for surviving repository '{name}'")
            if storage["blobStoreName"] in selected_blobs:
                raise CleanupError(f"Blob store is still used by surviving repository '{name}'")

    ordered_repositories = _ordered_repositories(session, base_url, repo_map, repositories)
    return ordered_repositories, list(blobstores)


def execute_cleanup(session, base_url, repositories, blobstores):
    """Delete planned repositories before blob stores; stop immediately on errors."""
    for name in repositories:
        response = session.delete(f"{base_url}/service/rest/v1/repositories/{quote(name, safe='')}")
        response.raise_for_status()
        logger.info("Deleted repository '%s'", name)
    for name in blobstores:
        response = session.delete(f"{base_url}/service/rest/v1/blobstores/{quote(name, safe='')}")
        response.raise_for_status()
        logger.info("Deleted blob store '%s'", name)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Preview-first Nexus repository and blob store cleanup")
    parser.add_argument("--config-dir", default="config.d")
    parser.add_argument("--repository", action="append", default=[], help="Exact configured repository name")
    parser.add_argument("--blobstore", action="append", default=[], help="Exact configured blob store name")
    mode_flags = parser.add_mutually_exclusive_group()
    mode_flags.add_argument("--managed", action="store_true", help="All configured resources on Nexus")
    mode_flags.add_argument("--all", action="store_true", help="ALL Nexus repositories and non-default blobs")
    parser.add_argument("--apply", action="store_true", help="Actually delete the planned resources")
    parser.add_argument("--confirm-target", help="Required with --apply: exact Nexus base URL")
    parser.add_argument("--confirm-phrase", help="Required with --apply for --managed or --all")
    args = parser.parse_args(argv)

    try:
        if (args.managed or args.all) and (args.repository or args.blobstore):
            raise CleanupError("Bulk modes cannot be combined with --repository or --blobstore")
        mode = "all" if args.all else "managed" if args.managed else "selective"
        expected_phrase = CONFIRM_PHRASES.get(mode)
        if args.apply and expected_phrase and args.confirm_phrase != expected_phrase:
            raise CleanupError(f"--{mode} --apply requires --confirm-phrase {expected_phrase}")
        if args.confirm_phrase is not None and (not args.apply or not expected_phrase):
            raise CleanupError("--confirm-phrase is only valid with bulk --apply")
        if not args.apply and args.confirm_target is not None:
            raise CleanupError("--confirm-target is only valid together with --apply")

        config = load_config_from_dir(args.config_dir)
        config, secrets = resolve_nexus_credentials(config)
        # Full cleanup needs only connection configuration. Do not force
        # unrelated repository / S3 environment references to be available.
        if mode == "all":
            connection = {"nexus": config.get("nexus")}
            connection, extra = resolve_environment_references(connection)
            config = dict(config)
            config["nexus"] = connection["nexus"]
            validated = connection
        else:
            config, extra = resolve_environment_references(config)
            validated = config
        configure_log_redaction(secrets + extra)
        errors = validate_config(validated, FORMAT_MODULE_MAP)
        if errors:
            raise CleanupError("Invalid configuration: " + "; ".join(errors))
        url = config["nexus"]["url"].rstrip("/")
        if args.apply and args.confirm_target != url:
            raise CleanupError("Deletion requires --confirm-target matching the exact Nexus URL")
        session = build_session(config["nexus"])
        if not verify_connection(session, url):
            raise CleanupError("Unable to verify Nexus connection")
        repos, blobs = plan_cleanup(session, url, config, args.repository, args.blobstore, mode=mode)
        logger.info("Cleanup mode: %s; %s repositories and %s blob stores selected",
                    mode, len(repos), len(blobs))
        for name in repos:
            logger.info("%s repository: %s", "DELETE" if args.apply else "PLAN", name)
        for name in blobs:
            logger.info("%s blob store: %s", "DELETE" if args.apply else "PLAN", name)
        if args.apply:
            execute_cleanup(session, url, repos, blobs)
        else:
            extra_confirmation = (f" --confirm-phrase {expected_phrase}"
                                  if expected_phrase else "")
            logger.info("Preview only; no deletions. To execute, add --apply "
                        "--confirm-target '%s'%s", url, extra_confirmation)
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
