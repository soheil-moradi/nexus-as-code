"""Local configuration checks performed before any Nexus API calls.

This validates the shared fields used by the orchestrator. Format-specific Nexus
API schemas are intentionally outside this module's scope.
"""

from urllib.parse import urlsplit


REPOSITORY_TYPES = {"hosted", "proxy", "group"}
BLOB_TYPES = {"file", "s3"}


def _required_string(item, field, location, errors):
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{location}.{field}: required non-empty string")
        return None
    return value


def _optional_string(item, field, location, errors):
    if field in item:
        _required_string(item, field, location, errors)


def _url(item, field, location, errors):
    value = _required_string(item, field, location, errors)
    if value is None:
        return
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.port != 0
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        errors.append(f"{location}.{field}: expected an HTTP(S) URL without credentials or query")


def validate_config(config, formats):
    """Return validation errors (empty list means valid); never contacts Nexus."""
    errors = []
    if not isinstance(config, dict):
        return ["configuration: expected a mapping"]

    for section in config:
        if section not in {"nexus", "blobs", "repositories"}:
            errors.append(f"configuration: unknown section '{section}'")

    nexus = config.get("nexus")
    if not isinstance(nexus, dict):
        errors.append("nexus: required mapping")
    else:
        _url(nexus, "url", "nexus", errors)
        _required_string(nexus, "username", "nexus", errors)
        _required_string(nexus, "password", "nexus", errors)

    blobs = config.get("blobs", [])
    if not isinstance(blobs, list):
        errors.append("blobs: expected a list")
    else:
        seen_blobs = {}
        for index, blob in enumerate(blobs):
            location = f"blobs[{index}]"
            if not isinstance(blob, dict):
                errors.append(f"{location}: expected a mapping")
                continue
            name = _required_string(blob, "name", location, errors)
            if name is not None:
                if name in seen_blobs:
                    errors.append(f"{location}.name: duplicate blob store '{name}' (first: {seen_blobs[name]})")
                else:
                    seen_blobs[name] = location
            blob_type = blob.get("type", "file")
            if not isinstance(blob_type, str) or blob_type.lower() not in BLOB_TYPES:
                errors.append(f"{location}.type: expected 'file' or 's3'")
            elif blob_type.lower() == "s3":
                _required_string(blob, "bucket", location, errors)
                provider = blob.get("s3_provider", "aws")
                if not isinstance(provider, str) or provider.lower() not in {"aws", "minio"}:
                    errors.append(f"{location}.s3_provider: expected 'aws' or 'minio'")
                elif provider.lower() == "minio":
                    _url(blob, "endpoint", location, errors)
            _optional_string(blob, "path", location, errors)

    repositories = config.get("repositories", {})
    if not isinstance(repositories, dict):
        errors.append("repositories: expected a mapping")
    else:
        seen_repos = {}
        for fmt, entries in repositories.items():
            location = f"repositories.{fmt}"
            if not isinstance(fmt, str) or fmt not in formats:
                errors.append(f"{location}: unknown repository format")
            if not isinstance(entries, list):
                errors.append(f"{location}: expected a list")
                continue
            for index, repo in enumerate(entries):
                item_location = f"{location}[{index}]"
                if not isinstance(repo, dict):
                    errors.append(f"{item_location}: expected a mapping")
                    continue
                name = _required_string(repo, "name", item_location, errors)
                if name is not None:
                    if name in seen_repos:
                        errors.append(
                            f"{item_location}.name: duplicate repository '{name}' "
                            f"(first: {seen_repos[name]})"
                        )
                    else:
                        seen_repos[name] = item_location
                repo_type = _required_string(repo, "type", item_location, errors)
                if repo_type is not None:
                    if repo_type.lower() not in REPOSITORY_TYPES:
                        errors.append(f"{item_location}.type: expected hosted, proxy or group")
                    elif repo_type.lower() == "proxy":
                        _url(repo, "remote_url", item_location, errors)
                    elif repo_type.lower() == "group":
                        members = repo.get("members")
                        if (not isinstance(members, list) or not members or
                                any(not isinstance(m, str) or not m.strip() for m in members)):
                            errors.append(f"{item_location}.members: expected a non-empty list of names")
                _optional_string(repo, "blob_store", item_location, errors)

    return errors
