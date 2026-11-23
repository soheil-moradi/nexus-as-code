#!/usr/bin/env python3
"""
main.py - Nexus 3 Configuration Tool
Reads multiple YAML config files from a directory and provisions blob stores + repositories.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, Any

import requests
import yaml

# ============================================================
#  Dynamic module loading
# ============================================================
import importlib

FORMAT_MODULE_MAP = {
    "apt":       "apt",
    "npm":       "npm",
    "conda":     "conda",
    "r":         "r",
    "pypi":      "pypi",
    "maven":     "maven",
    "raw":       "raw",
    "docker":    "docker",
    "cargo":     "cargo",
    "swift":     "swift",
    "terraform": "terraform",
    "go":        "go",
    "helm":      "helm",
    "nuget":     "nuget",
    "conan":     "conan",
    "rubygems":  "rubygems",
    "yum":       "yum",
    "cocoapods": "cocoapods",
    "gitlfs":    "gitlfs",
    "p2":        "p2",
    "alpine":    "alpine",
    "ansible":   "ansible",
}

def load_module(format_name: str):
    module_name = FORMAT_MODULE_MAP.get(format_name)
    if not module_name:
        return None
    try:
        return importlib.import_module(f"modules.{module_name}")
    except ImportError:
        return None

# ============================================================
#  Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s – %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")

# ============================================================
#  Config loading
# ============================================================

def load_config_from_dir(config_dir: str) -> Dict[str, Any]:
    base_path = Path(config_dir)
    if not base_path.exists():
        logger.error(f"Config directory '{config_dir}' not found.")
        sys.exit(1)

    merged = {}
    yaml_files = sorted(base_path.glob("*.yml")) + sorted(base_path.glob("*.yaml"))
    if not yaml_files:
        logger.error(f"No .yml or .yaml files found in '{config_dir}'.")
        sys.exit(1)

    for file_path in yaml_files:
        with file_path.open("r") as fh:
            data = yaml.safe_load(fh) or {}
        for key, value in data.items():
            if key == "repositories":
                if not isinstance(value, dict):
                    logger.error(f"Invalid 'repositories' section in '{file_path.name}': expected a mapping.")
                    sys.exit(1)
                repo_configs = merged.setdefault("repositories", {})
                for fmt, repos in value.items():
                    if not isinstance(repos, list):
                        logger.error(
                            f"Invalid '{fmt}' repositories in '{file_path.name}': expected a list."
                        )
                        sys.exit(1)
                    repo_configs.setdefault(fmt, []).extend(repos)
            elif key in merged:
                if isinstance(merged[key], dict) and isinstance(value, dict):
                    merged[key].update(value)
                elif isinstance(merged[key], list) and isinstance(value, list):
                    merged[key].extend(value)
                else:
                    merged[key] = value
            else:
                merged[key] = value
        logger.debug(f"Merged '{file_path.name}'")

    if "nexus" not in merged:
        logger.error("No 'nexus' configuration found in any file.")
        sys.exit(1)
    return merged

# ============================================================
#  Core functions
# ============================================================

def build_session(nexus_cfg: dict) -> requests.Session:
    session = requests.Session()
    session.auth = (nexus_cfg["username"], nexus_cfg["password"])
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    return session

def verify_connection(session: requests.Session, base_url: str) -> bool:
    try:
        resp = session.get(f"{base_url}/service/rest/v1/status", timeout=10)
        if resp.status_code == 200:
            logger.info(f"Connected to Nexus at {base_url}")
            return True
        logger.error(f"Nexus returned HTTP {resp.status_code} – check credentials.")
    except requests.ConnectionError as exc:
        logger.error(f"Cannot reach Nexus at {base_url}: {exc}")
    return False

def blob_store_exists(session, base_url: str, name: str) -> bool:
    url = f"{base_url}/service/rest/v1/blobstores"
    resp = session.get(url)
    resp.raise_for_status()
    return any(b.get("name") == name for b in resp.json())

def provision_blobs(session, base_url: str, blob_list: list, dry_run: bool) -> tuple:
    import blobs
    ok = failed = 0
    for blob in blob_list:
        name = blob.get("name", "<unnamed>")
        blob_type = blob.get("type", "file")
        if dry_run:
            logger.info(f"[DRY-RUN] Would create {blob_type} blob store '{name}'.")
            ok += 1
            continue
        if blobs.create_blob_store(session, base_url, blob):
            ok += 1
        else:
            failed += 1
    return ok, failed

def provision_repositories(session, base_url: str, repo_cfg: dict, dry_run: bool) -> tuple:
    ok = failed = 0
    for fmt, repo_list in repo_cfg.items():
        module = load_module(fmt)
        if module is None:
            logger.warning(f"No handler for format '{fmt}' – skipping.")
            continue
        if not hasattr(module, "create_repository"):
            logger.warning(f"Module for '{fmt}' missing create_repository() – skipping.")
            continue

        for repo in repo_list:
            name = repo.get("name", "<unnamed>")
            repo_type = repo.get("type", "?")
            blob_store = repo.get("blob_store", "default")

            if not dry_run and not blob_store_exists(session, base_url, blob_store):
                logger.error(f"Blob store '{blob_store}' not found – skipping repo '{name}'")
                failed += 1
                continue

            if dry_run:
                logger.info(f"[DRY-RUN] Would create {fmt} {repo_type} repo '{name}'.")
                ok += 1
                continue

            if module.create_repository(session, base_url, repo):
                ok += 1
            else:
                failed += 1
    return ok, failed

# ============================================================
#  CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Provision Nexus 3 from a directory of YAML configs."
    )
    parser.add_argument(
        "--config-dir", default="config.d",
        help="Directory containing YAML config files (default: config.d)",
    )
    parser.add_argument(
        "--blobs-only", action="store_true",
        help="Only create blob stores, skip repositories",
    )
    parser.add_argument(
        "--repos-only", action="store_true",
        help="Only create repositories, skip blob stores",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be created without making API calls",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Enable debug-level logging",
    )
    return parser.parse_args()

def main() -> None:
    args = parse_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.blobs_only and args.repos_only:
        logger.error("Cannot use --blobs-only and --repos-only together.")
        sys.exit(1)

    config = load_config_from_dir(args.config_dir)
    nexus_cfg = config.get("nexus", {})
    base_url = nexus_cfg.get("url", "http://localhost:8081").rstrip("/")

    session = build_session(nexus_cfg)

    if not args.dry_run and not verify_connection(session, base_url):
        sys.exit(1)

    total_ok = total_failed = 0

    if not args.repos_only:
        blob_list = config.get("blobs", [])
        if blob_list:
            logger.info(f"=== Provisioning {len(blob_list)} blob store(s) ===")
            ok, failed = provision_blobs(session, base_url, blob_list, args.dry_run)
            total_ok += ok
            total_failed += failed
        else:
            logger.info("No blob stores defined – skipping.")

    if not args.blobs_only:
        repo_cfg = config.get("repositories", {})
        if repo_cfg:
            total_repos = sum(len(v) for v in repo_cfg.values())
            logger.info(f"=== Provisioning {total_repos} repository/ies ===")
            ok, failed = provision_repositories(session, base_url, repo_cfg, args.dry_run)
            total_ok += ok
            total_failed += failed
        else:
            logger.info("No repositories defined – skipping.")

    logger.info("─" * 50)
    logger.info(f"Done.  ✔ {total_ok} succeeded   ✘ {total_failed} failed")
    if total_failed:
        sys.exit(1)

if __name__ == "__main__":
    main()