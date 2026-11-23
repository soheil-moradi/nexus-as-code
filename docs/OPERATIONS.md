# Operations, safety, and verification

This document describes the behavior of `nexus-as-code` after its code-hardening
changes. No client-side APT installer is included. The project configures Nexus
repository and blob store resources; it does not deploy or operate Nexus itself.

## Supported operations

- **Create-only:** An existing repository or blob store is treated as already
  provisioned. The tool does not compare or update its existing settings.
- **Supported formats:** See the matrix in the root README. The matrix reflects
  implemented handlers, not a guarantee that any given Nexus version/edition
  exposes the required API endpoints. Git LFS is **hosted only**.
- **Dry-run:** Local YAML and handler checks with **zero Nexus HTTP requests**.
  The count indicates planned operations. No live remote-state checks are made.
- **Live run:** Reads remote inventories, skips pre-existing resources and
  creates missing ones. Creation is **not atomic**; failures can leave already
  created resources in place. Non-zero exit status indicates reported failures.

## Setting up private configuration

Keep all private configuration outside this public checkout. The tracked
`config.d/*.yml` files are examples, not a safe place for production secrets.

```bash
mkdir -p "$HOME/.config"
cp -a config.d "$HOME/.config/nexus-as-code"
vim "$HOME/.config/nexus-as-code/00-nexus.yml"

export NEXUS_USERNAME='my-nexus-user'
read -rsp 'Nexus password: ' NEXUS_PASSWORD; echo
export NEXUS_PASSWORD

python3 main.py --config-dir "$HOME/.config/nexus-as-code" --dry-run
python3 main.py --config-dir "$HOME/.config/nexus-as-code"
```

The two `NEXUS_*` environment values override their respective YAML fields.
For any other YAML value that must be passed securely (S3 credentials, APT
private signing key, signing passphrase), use a complete environment reference:

```yaml
blobs:
  - name: external-s3
    type: s3
    bucket: artifacts-example
    access_key_id: "${ENV:S3_ACCESS_KEY_ID}"
    secret_access_key: "${ENV:S3_SECRET_ACCESS_KEY}"
```

Log messages and tracebacks mask configured credentials. Values shorter than
four characters are masked only when they occur as separate tokens, to avoid
mangling normal words (for example, a one-letter test username must not alter
"repository"). Embedded occurrences of very short credentials cannot always be
recognized unambiguously; use strong, longer passwords and avoid including
secrets in URLs or log messages.

Environment variables are inherited by child processes and may be visible to
privileged local observers. Use an approved secret provider for high-security
environments; this tool does not implement a separate secret manager. Never put
credentials in an HTTP URL. An unset/empty referenced variable produces an
error **before** any resource-creation requests.

## Ordering, errors, timeouts

- YAML files are processed in one lexicographic order across `.yml` and
  `.yaml`; repository lists of the same format are merged.
- Duplicate YAML mapping keys, duplicate resource names, malformed values,
  unsupported format/type combinations, and local group dependency cycles are
  rejected before provisioning.
- Hosted/proxy repositories are created before local group dependencies.
  Group creation is skipped if a locally configured member failed earlier.
  Members that exist only on the Nexus instance are allowed but validated by
  Nexus when the group is created.
- Every HTTP request made through the shared Nexus session has a default
  **5-second connection / 30-second read timeout**. Read-only GET/HEAD requests
  have at most two automatic retries on temporary failures. POST/DELETE
  operations are **not** retried, because their result may be uncertain after
  a network failure.
- Blob store existence is cached during a provisioning pass; on subsequent
  runs the server is queried again. Other repository existence checks are
  carried out by their format modules.
- If one creation fails, later independent creations continue; the final
  process exit code is non-zero. There is **no transaction rollback**.

## APT-specific notes

APT `hosted` requires an explicit `distribution` and `signing_keypair`; the
signing passphrase may be empty for an unencrypted private key. APT `proxy` has
no hardcoded `bionic` default. Its `distribution` may be set (e.g., `jammy`,
`noble`, `bookworm`, `trixie`) or omitted/empty for multi-distribution mode, if
supported by the Nexus version/configuration. `enforce_distribution` defaults
false; setting it true requires an explicit distribution. APT Group is unsupported.
Re-signing, pass-through metadata and actual `apt update` / `apt install`
behavior require verification against your chosen Nexus installation.

## Cleaner: selective, managed, and full cleanup

`nexus_cleaner.py` is a **destructive administrative utility** with three
explicit modes. Preview is the default for *all* modes and performs reads only.
No mode makes DELETE requests without `--apply` and a matching
`--confirm-target` URL. There is no `--password` CLI argument; use
`NEXUS_USERNAME`/`NEXUS_PASSWORD` or private configuration.

| Mode | Selection | Additional confirmation for `--apply` |
| --- | --- | --- |
| Selective (default) | Explicit `--repository NAME` / `--blobstore NAME`, both must appear in YAML and exist remotely | None beyond exact target URL |
| `--managed` | All YAML-defined repositories and non-default blob stores that currently exist on Nexus | `--confirm-phrase DELETE-MANAGED` |
| `--all` | **All** Nexus repositories and **all non-default** blob stores, whether in YAML or not | `--confirm-phrase DELETE-ALL` |

**The `default` blob store is always protected**, including in full mode.
`--managed` and `--all` cannot be combined with named-resource selection or
with each other. Missing managed resources are skipped so partial cleanup can
be resumed. Full cleanup validates connection settings but doesn't require
locally configured repositories to match the remote inventory.

### Preview commands (non-destructive)

```bash
python3 nexus_cleaner.py --config-dir "$HOME/.config/nexus-as-code" \
  --repository npm-proxy-official
python3 nexus_cleaner.py --config-dir "$HOME/.config/nexus-as-code" --managed
python3 nexus_cleaner.py --config-dir "$HOME/.config/nexus-as-code" --all
```

### Deletion commands (destructive; examples only)

**Never run these against a production Nexus without a verified backup and
reviewing the corresponding preview.** The confirmed target must exactly match
the URL from the selected private `00-nexus.yml` (without a trailing slash).

```bash
# Delete a single configured repository
python3 nexus_cleaner.py --config-dir "$HOME/.config/nexus-as-code" \
  --repository npm-proxy-official --apply \
  --confirm-target https://nexus.example.com

# Delete every existing, configured repository and non-default blob store
python3 nexus_cleaner.py --config-dir "$HOME/.config/nexus-as-code" \
  --managed --apply --confirm-target https://nexus.example.com \
  --confirm-phrase DELETE-MANAGED

# Delete ALL Nexus repositories and non-default blob stores, including unmanaged
python3 nexus_cleaner.py --config-dir "$HOME/.config/nexus-as-code" \
  --all --apply --confirm-target https://nexus.example.com \
  --confirm-phrase DELETE-ALL
```

The cleaner reads Nexus inventories for both repositories and blob stores. It
checks live membership of surviving Groups before deleting selected members;
selected nested Groups are ordered parents-first. Before deleting selected blob
stores, it checks storage mappings on **all surviving repositories**, including
unmanaged ones. Unknown dependencies or failed inspection **stop the cleanup**.
All repository DELETE operations are performed before blob store DELETEs.
Each DELETE is non-retried; the first error aborts execution, with any already
deleted resources **not** restored. These checks cannot prevent races with
other administrators or guarantee a consistent full inventory with insufficient
permissions. Do not perform concurrent administrative changes. Full cleanup
can permanently destroy artifacts in hosted stores as well as cached artifacts.
Nexus backup/restore is outside this tool's scope.

Existing format support and Create-only provisioning are unchanged. Git LFS
remains Hosted-only. The client-side APT installer is a separate project.

## GitHub Actions scope

`.github/workflows/python-ci.yml` runs Python 3.10 and 3.12 checks on pushes
and pull requests: critical Flake8 diagnostics, Python compilation, local
unittest discovery, and an **offline** `main.py --dry-run`. The workflow uses
read-only repository permissions and does **not** provision or clean a Nexus
instance, consume Nexus credentials, or implement application deployment.

## Running local tests

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q main.py blobs.py config_validation.py config_secrets.py nexus_cleaner.py modules tests
python3 main.py --dry-run
git diff --check
```

Unit tests exercise validation, HTTP configuration, deletion safety and mocked
REST calls across the tracked example repositories. **These are not live Nexus
integration tests.** Before using this against a production Nexus, manually
check the version-specific REST schema at
`https://YOUR-NEXUS/service/rest/swagger.json` and test the create-and-fetch
path against a disposable Nexus instance. Confirm that a second run skips
resources safely. Use backups and least-privileged credentials.

## Limitations

- No automatic update of existing configuration (no drift reconciliation).
- No transaction rollback or automated backup/restore.
- Format availability, exact API payload fields and access permissions depend
  on the live Nexus version and edition and are not verified offline.
- This project does not configure APT clients or Docker build environments.
- The tracked Alpine example remains unchanged; production signing behavior is
  not covered by current tests against a running Nexus.
