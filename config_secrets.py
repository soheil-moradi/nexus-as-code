"""Resolve explicitly marked environment values without exposing them in errors."""

import os
import re

REFERENCE = re.compile(r"^\$\{ENV:([A-Za-z_][A-Za-z_0-9]*)\}$")
SECRET_FIELDS = ("password", "passphrase", "secret", "token", "keypair", "access_key", "credential")


def resolve_environment_references(config):
    """Replace exact ${ENV:NAME} placeholders and return a copy plus redaction values.

    Missing or empty variables fail closed. Embedded substitution is intentionally
    unsupported, so no shell expansion or arbitrary interpolation is performed.
    """
    sensitive = []

    def walk(value, path="configuration", field=""):
        if isinstance(value, dict):
            return {key: walk(item, f"{path}.{key}", str(key)) for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item, f"{path}[{index}]", field) for index, item in enumerate(value)]
        if isinstance(value, str):
            if any(word in field.lower() for word in SECRET_FIELDS) and value:
                sensitive.append(value)
            match = REFERENCE.fullmatch(value)
            if match:
                name = match.group(1)
                replacement = os.environ.get(name)
                if not replacement:
                    raise ValueError(f"{path}: environment variable '{name}' is missing or empty")
                sensitive.append(replacement)
                return replacement
            if "${ENV:" in value:
                raise ValueError(f"{path}: expected an exact '${{ENV:VARIABLE}}' reference")
        return value

    result = walk(config)
    return result, sensitive
