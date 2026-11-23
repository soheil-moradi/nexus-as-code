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

## Safe cleaner

`nexus_cleaner.py` is a separate, intentionally destructive utility.
It defaults to preview; only explicit names that are present in your chosen
YAML config are accepted. It does **not** expose a delete-all option.

```bash
python3 nexus_cleaner.py --config-dir "$HOME/.config/nexus-as-code" \
  --repository npm-proxy-official

# Only after inspecting the preview:
python3 nexus_cleaner.py --config-dir "$HOME/.config/nexus-as-code" \
  --repository npm-proxy-official --apply \
  --confirm-target https://nexus.example.com
```

A blob store requires its own `--blobstore NAME` selection; `default` is always
protected. Before deleting a blob store the tool looks at the detailed storage
configuration for **every surviving repository**, and refuses deletion if a
mapping is unknown or still in use. Before deleting a selected repository it
also inspects surviving Groups for references to that name. Failure to read
these dependencies stops the operation. The checks are not an atomic snapshot:
concurrent modifications made by other admins cannot be prevented by the
script. Avoid concurrent administrative changes during deletion. Failed
DELETE requests are **not** automatically retried. Cleanup is irreversible;
restore requires Nexus backups and is not implemented here.

Legacy CLI options such as `--password` and a broad `--confirm` deletion were
removed for safety. Set `NEXUS_USERNAME` and `NEXUS_PASSWORD` or supply private
YAML credentials only from outside the public checkout.

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
