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

from config_validation import validate_config

# ============================================================
#  Dynamic module loading
# ============================================================
import importlib
import os
import re
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from config_secrets import resolve_environment_references

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
    except ImportError as exc:
        logger.error("Cannot import handler for format '%s': %s", format_name, exc)
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


class CredentialRedactingFormatter(logging.Formatter):
    """Mask credentials even when included in exception tracebacks or HTTP errors."""

    def __init__(self, formatter, values):
        super().__init__()
        self.formatter = formatter
        self.values = sorted(
            {value for value in values if isinstance(value, str) and value},
            key=len, reverse=True,
        )
        # Short test credentials such as "u" and "p" must not corrupt ordinary
        # log messages (e.g. "Cleanup refused" or "repository"). Match them
        # only as standalone tokens; longer secrets remain substring-masked.
        self.short_patterns = {
            value: re.compile(r"(?<!\w)" + re.escape(value) + r"(?!\w)")
            for value in self.values if len(value) < 4
        }

    def format(self, record):
        output = self.formatter.format(record)
        for value in self.values:
            if value in self.short_patterns:
                output = self.short_patterns[value].sub("[REDACTED]", output)
            else:
                output = output.replace(value, "[REDACTED]")
        return output


def configure_log_redaction(values):
    """Apply redaction to CLI logging handlers without changing their formatting."""
    for handler in logging.getLogger().handlers:
        formatter = handler.formatter or logging.Formatter()
        if isinstance(formatter, CredentialRedactingFormatter):
            formatter = formatter.formatter
        handler.setFormatter(CredentialRedactingFormatter(formatter, values))


def resolve_nexus_credentials(config):
    """Environment overrides YAML per field; explicit empty values remain invalid."""
    nexus = config.get("nexus")
    if not isinstance(nexus, dict):
        return config, []

    resolved = dict(nexus)
    secrets = [nexus.get("username"), nexus.get("password")]
    for field, env_var in (("username", "NEXUS_USERNAME"), ("password", "NEXUS_PASSWORD")):
        if env_var in os.environ:
            resolved[field] = os.environ[env_var]
            secrets.append(os.environ[env_var])

    config = dict(config)
    config["nexus"] = resolved
    return config, secrets

# ============================================================
#  Config loading
# ============================================================

class UniqueKeysSafeLoader(yaml.SafeLoader):
    """Use the safe YAML loader, but reject duplicate explicit mapping keys."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            # YAML merge keys may legitimately be overridden explicitly.
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping", node.start_mark,
                    "duplicate YAML mapping key", key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def load_config_from_dir(config_dir: str) -> Dict[str, Any]:
    base_path = Path(config_dir)
    if not base_path.exists():
        logger.error(f"Config directory '{config_dir}' not found.")
        sys.exit(1)

    merged = {}
    yaml_files = sorted((*base_path.glob("*.yml"), *base_path.glob("*.yaml")))
    if not yaml_files:
        logger.error(f"No .yml or .yaml files found in '{config_dir}'.")
        sys.exit(1)

    for file_path in yaml_files:
        try:
            with file_path.open("r", encoding="utf-8") as fh:
                data = yaml.load(fh, Loader=UniqueKeysSafeLoader)
        except (yaml.YAMLError, ValueError, TypeError) as exc:
            mark = getattr(exc, "problem_mark", None)
            location = f" at line {mark.line + 1}" if mark is not None else ""
            logger.error(f"Invalid YAML in '{file_path.name}'{location}.")
            sys.exit(1)
        except OSError as exc:
            logger.error(f"Cannot read '{file_path.name}': {exc}")
            sys.exit(1)
        if not isinstance(data, dict):
            logger.error(f"Invalid YAML in '{file_path.name}': expected a mapping.")
            sys.exit(1)
        for key, value in data.items():
            if key not in {"nexus", "blobs", "repositories"}:
                logger.error(f"Unknown configuration section '{key}' in '{file_path.name}'.")
                sys.exit(1)
            if key == "nexus" and not isinstance(value, dict):
                logger.error(f"Invalid 'nexus' section in '{file_path.name}': expected a mapping.")
                sys.exit(1)
            if key == "blobs" and not isinstance(value, list):
                logger.error(f"Invalid 'blobs' section in '{file_path.name}': expected a list.")
                sys.exit(1)
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
        logger.debug("Merged '%s'", file_path.name)

    if "nexus" not in merged:
        logger.error("No 'nexus' configuration found in any file.")
        sys.exit(1)
    return merged

# ============================================================
#  Core functions
# ============================================================

class NexusSession(requests.Session):
    """Bound every request; retry safe reads only, never write operations."""

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", (5, 30))
        return super().request(method, url, **kwargs)


def build_session(nexus_cfg: dict) -> requests.Session:
    session = NexusSession()
    retries = Retry(
        total=2,
        backoff_factor=0.5,
        status_forcelist=(429, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        respect_retry_after_header=True,
    )
    session.mount("http://", HTTPAdapter(max_retries=retries))
    session.mount("https://", HTTPAdapter(max_retries=retries))
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
    except requests.RequestException:
        logger.error("Cannot reach Nexus at %s (network or HTTP error).", base_url)
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
        try:
            created = blobs.create_blob_store(session, base_url, blob)
        except Exception:
            logger.exception("Failed to provision blob store '%s'.", name)
            failed += 1
            continue
        if created:
            ok += 1
        else:
            failed += 1
    return ok, failed

def order_repository_definitions(repo_cfg: dict) -> dict:
    """Create hosted/proxy dependencies before groups (including nested groups)."""
    ordered = {}
    for fmt, entries in repo_cfg.items():
        remaining = list(entries)
        result = []
        while remaining:
            names = {item.get("name") for item in remaining}
            ready = next((
                index for index, item in enumerate(remaining)
                if item.get("type", "").lower() != "group"
                or not any(member in names for member in item.get("members", []))
            ), None)
            if ready is None:
                raise ValueError(f"Cyclic group dependency for format '{fmt}'")
            result.append(remaining.pop(ready))
        ordered[fmt] = result
    return ordered


def provision_repositories(session, base_url: str, repo_cfg: dict, dry_run: bool) -> tuple:
    ok = failed = 0
    blob_lookup = {}
    failed_names = set()
    repo_cfg = order_repository_definitions(repo_cfg)
    for fmt, repo_list in repo_cfg.items():
        try:
            module = load_module(fmt)
        except Exception:
            logger.exception("Cannot load handler for format '%s'.", fmt)
            failed += len(repo_list)
            continue
        if module is None:
            logger.error("No handler for format '%s'; %d repository/ies failed.", fmt, len(repo_list))
            failed += len(repo_list)
            continue
        create_repository = getattr(module, "create_repository", None)
        if not callable(create_repository):
            logger.error("Handler for '%s' has no callable create_repository(); "
                         "%d repository/ies failed.", fmt, len(repo_list))
            failed += len(repo_list)
            continue

        for repo in repo_list:
            name = repo.get("name", "<unnamed>")
            repo_type = repo.get("type", "?")
            blob_store = repo.get("blob_store", "default")

            if str(repo_type).lower() == "group" and any(member in failed_names for member in repo.get("members", [])):
                logger.error("Cannot create group '%s': a configured member failed.", name)
                failed += 1
                failed_names.add(name)
                continue

            if not dry_run:
                try:
                    if blob_store not in blob_lookup:
                        blob_lookup[blob_store] = blob_store_exists(session, base_url, blob_store)
                    exists = blob_lookup[blob_store]
                except Exception:
                    logger.exception("Cannot check blob store '%s' for repository '%s'.", blob_store, name)
                    failed += 1
                    failed_names.add(name)
                    continue
                if not exists:
                    logger.error("Blob store '%s' not found – skipping repo '%s'", blob_store, name)
                    failed += 1
                    failed_names.add(name)
                    continue

            if dry_run:
                logger.info("[DRY-RUN] Would create %s %s repo '%s'.", fmt, repo_type, name)
                ok += 1
                continue

            try:
                created = create_repository(session, base_url, repo)
            except Exception:
                logger.exception("Failed to provision %s repository '%s'.", fmt, name)
                failed += 1
                failed_names.add(name)
                continue
            if created:
                ok += 1
            else:
                logger.error("Failed to provision %s repository '%s'.", fmt, name)
                failed += 1
                failed_names.add(name)
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
    config, sensitive_values = resolve_nexus_credentials(config)
    try:
        config, extra_secrets = resolve_environment_references(config)
    except ValueError as exc:
        configure_log_redaction(sensitive_values)
        logger.error("Invalid configuration: %s", exc)
        sys.exit(1)
    sensitive_values.extend(extra_secrets)
    configure_log_redaction(sensitive_values)
    validation_errors = validate_config(config, FORMAT_MODULE_MAP)
    if validation_errors:
        for error in validation_errors:
            logger.error(f"Invalid configuration: {error}")
        sys.exit(1)
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
    if args.dry_run:
        logger.info("Dry-run only: %d planned, %d rejected; no Nexus changes made.", total_ok, total_failed)
    else:
        logger.info("Done.  ✔ %d completed   ✘ %d failed", total_ok, total_failed)
    if total_failed:
        sys.exit(1)

if __name__ == "__main__":
    main()