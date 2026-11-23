<!-- ============================================================ -->
<!-- BADGES                                                        -->
<!-- ============================================================ -->

<div align="center">

# 🚀 nexus-as-code

[![GitHub release](https://img.shields.io/github/v/release/soheil-moradi/nexus-as-code?style=flat-square&logo=github)](https://github.com/soheil-moradi/nexus-as-code/releases)
[![Python](https://img.shields.io/badge/python-3.8+-blue?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square&logo=opensourceinitiative&logoColor=white)](https://opensource.org/licenses/MIT)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen?style=flat-square&logo=github&logoColor=white)](https://github.com/soheil-moradi/nexus-as-code/pulls)
[![GitHub issues](https://img.shields.io/github/issues/soheil-moradi/nexus-as-code?style=flat-square&logo=github)](https://github.com/soheil-moradi/nexus-as-code/issues)
[![GitHub stars](https://img.shields.io/github/stars/soheil-moradi/nexus-as-code?style=flat-square&logo=github)](https://github.com/soheil-moradi/nexus-as-code/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/soheil-moradi/nexus-as-code?style=flat-square&logo=github)](https://github.com/soheil-moradi/nexus-as-code/network/members)

**Provision Nexus 3 Blob Stores and Repositories using YAML – Infrastructure as Code for Sonatype Nexus**

</div>

---

## ✨ Key Features

- ✅ Supports **22 repository formats** (all major formats except Bower).
- ✅ Supports **Hosted**, **Proxy**, and **Group** repository types (wherever Nexus supports them).
- ✅ **Modular Configuration**: Split your configuration into multiple smaller YAML files inside a directory.
- ✅ **Blob Store Validation**: Automatically checks if a blob store exists before creating a repository.
- ✅ **Docker Path-Based Routing Fix**: Automatically handles `subdomain: null` for proper Path-Based Routing.
- ✅ Supports **File**, **AWS S3**, and **MinIO** Blob Stores.
- ✅ **Dry-Run Mode**: Preview all changes without applying them.
- ✅ **Debug Logging**: Detailed logs for troubleshooting.
- ✅ Fully **Stateless** and CI/CD friendly.

---

## 📦 Supported Repository Formats

| Format | Hosted | Proxy | Group | Notes |
| :--- | :---: | :---: | :---: | :--- |
| **APT** | ✅ | ✅ | ❌ | Debian/Ubuntu repositories |
| **NPM** | ✅ | ✅ | ✅ | Node.js packages |
| **PyPI** | ✅ | ✅ | ✅ | Python packages |
| **Maven2** | ✅ | ✅ | ✅ | Java libraries |
| **Docker / OCI** | ✅ | ✅ | ✅ | With Path-Based Routing support |
| **Yum (RPM)** | ✅ | ✅ | ✅ | RPM repositories for Linux |
| **NuGet** | ✅ | ✅ | ✅ | .NET packages |
| **Conan (C/C++)** | ✅ | ✅ | ✅ | C/C++ packages |
| **Terraform** | ✅ | ✅ | ✅ | IaC modules and providers |
| **Helm (K8s)** | ✅ | ✅ | ✅ | Kubernetes charts |
| **R (CRAN)** | ✅ | ✅ | ✅ | R packages |
| **Conda** | ❌ | ✅ | ❌ | Proxy only (Nexus OSS limitation) |
| **Raw (Generic)** | ✅ | ✅ | ✅ | Any binary or generic file |
| **Cargo (Rust)** | ✅ | ✅ | ✅ | Rust packages |
| **Swift** | ✅ | ✅ | ✅ | Swift libraries |
| **Go** | ✅ | ✅ | ✅ | Go modules |
| **RubyGems** | ✅ | ✅ | ✅ | Ruby packages |
| **CocoaPods** | ✅ | ✅ | ✅ | iOS/macOS libraries |
| **Git LFS** | ✅ | ❌ | ❌ | Hosted only (per Nexus API) |
| **P2 (Eclipse)** | ✅ | ✅ | ✅ | Eclipse plugins |
| **Alpine (APK)** | ✅ | ✅ | ✅ | With Alpine signing support |
| **Ansible Galaxy** | ✅ | ✅ | ✅ | Ansible roles and collections |

---

## 📁 Project Structure

```
nexus-as-code/
├── main.py                 # Core orchestrator
├── blobs.py                # Blob Store management
├── requirements.txt        # Python dependencies
├── README.md               # This file
├── modules/                # Format-specific modules (22 total)
│   ├── __init__.py
│   ├── apt.py
│   ├── npm.py
│   ├── maven.py
│   ├── docker.py           # With Path-Based Routing fix
│   ├── yum.py
│   ├── nuget.py
│   ├── conan.py
│   ├── terraform.py
│   ├── helm.py
│   ├── r.py
│   ├── conda.py
│   ├── raw.py
│   ├── cargo.py
│   ├── swift.py
│   ├── go.py
│   ├── rubygems.py
│   ├── cocoapods.py
│   ├── gitlfs.py           # Hosted only
│   ├── p2.py
│   ├── alpine.py           # With AlpineSigning
│   └── ansible.py          # Format name: ansiblegalaxy
└── config.d/               # Modular configuration files
    ├── 00-nexus.yml          # Tracked sample; do not put secrets here
    ├── 10-blobs-common.yml   # Blob Store definitions
    ├── 20-repos-npm.yml
    ├── 21-repos-docker.yml
    ├── 22-repos-maven.yml
    └── ... (up to 22 separate files)
```

> **Note:** `config.d/*.yml` files in this repository are tracked. Keep real credentials and internal configuration out of your public Git history. See [Security](#security) below.

---

## 🚀 Installation & Setup

### 1. Prerequisites

- Python 3.8 or higher
- Access to Nexus Repository Manager 3 (version 3.20 or higher)
- Admin credentials or token with appropriate permissions

### 2. Clone & Install

```bash
git clone https://github.com/soheil-moradi/nexus-as-code.git
cd nexus-as-code
pip install -r requirements.txt
```

### 3. Configure Nexus Connection

Keep private settings outside the Git checkout. Copy the example configs to a
local directory and edit the Nexus URL (use Vim or your preferred editor):

```bash
mkdir -p "$HOME/.config"
cp -a config.d "$HOME/.config/nexus-as-code"
vim "$HOME/.config/nexus-as-code/00-nexus.yml"
```

```yaml
nexus:
  url: "https://nexus.example.com"
```

Provide Nexus credentials through environment variables (they override YAML
values independently). For an interactive Bash session, avoid putting the
password into shell history:

```bash
export NEXUS_USERNAME="your-nexus-user"
read -rsp "Nexus password: " NEXUS_PASSWORD; echo
export NEXUS_PASSWORD
```

Alternatively, `.env.example` documents the variable names; `.env` is ignored
by Git but is **not automatically loaded** by this tool. For backwards
compatibility, `nexus.username` and `nexus.password` in YAML still work, but
placing real credentials in tracked files is discouraged. An explicitly set
empty environment variable is invalid; it does not fall back to YAML.

### 4. Dry-Run (Preview)

Preview what the tool will do without making any changes:

```bash
python main.py --config-dir "$HOME/.config/nexus-as-code" --dry-run
```

### 5. Apply Configuration

Apply the configuration and provision everything:

```bash
python main.py --config-dir "$HOME/.config/nexus-as-code"
```

---

## 🛠️ Command-Line Options

| Option | Description |
| :--- | :--- |
| `--config-dir DIR` | Directory containing YAML config files (default: `config.d`) |
| `--blobs-only` | Only create blob stores, skip repositories |
| `--repos-only` | Only create repositories, skip blob stores |
| `--dry-run` | Preview changes without applying them |
| `--debug` | Enable debug-level logging |

---

## 📝 Writing Configuration Files

### 1. Nexus Connection (`00-nexus.yml`)

```yaml
nexus:
  url: "https://nexus.example.com"
  # username and password are supplied via NEXUS_USERNAME / NEXUS_PASSWORD.
```

### 2. Defining Blob Stores (`10-blobs-common.yml`)

**File Blob Store:**
```yaml
blobs:
  - name: "default"
    type: "file"
    path: "/nexus-data/blobs/default"

  - name: "docker-blob"
    type: "file"
    path: "/nexus-data/blobs/docker"
```

**AWS S3 Blob Store:**
```yaml
  - name: "s3-aws-blob"
    type: "s3"
    bucket: "my-nexus-bucket"
    region: "us-east-1"
    access_key_id: "AKIAIOSFODNN7EXAMPLE"
    secret_access_key: "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    prefix: "nexus/blobs"
    encryption: "s3ManagedEncryption"
```

**MinIO Blob Store:**
```yaml
  - name: "s3-minio-blob"
    type: "s3"
    s3_provider: "minio"
    bucket: "nexus-artifacts"
    endpoint: "http://minio.example.com:9000"
    access_key_id: "minioadmin"
    secret_access_key: "minioadmin"
    force_path_style: true
```

### 3. Defining Repositories

Each format can be placed in a separate file (e.g., `20-repos-npm.yml`):

**NPM Example:**
```yaml
repositories:
  npm:
    - name: "npm-proxy-official"
      type: "proxy"
      blob_store: "npm-blob"
      remote_url: "https://registry.npmjs.org"
    - name: "npm-hosted-private"
      type: "hosted"
      blob_store: "npm-blob"
      write_policy: "allow"
    - name: "npm-group-all"
      type: "group"
      blob_store: "npm-blob"
      members:
        - "npm-proxy-official"
        - "npm-hosted-private"
```

**Docker Example (Path-Based Routing):**
```yaml
repositories:
  docker:
    - name: "docker-proxy-hub"
      type: "proxy"
      blob_store: "docker-blob"
      connector: "path"           # Path-Based Routing (default)
      remote_url: "https://registry-1.docker.io"
      index_type: "HUB"
      foreign_layers: true
    - name: "docker-hosted-private"
      type: "hosted"
      blob_store: "docker-blob"
      connector: "path"
      write_policy: "allow"
```

**Maven Example (Version Policy):**
```yaml
repositories:
  maven:
    - name: "maven2-proxy-central"
      type: "proxy"
      blob_store: "maven-blob"
      remote_url: "https://repo1.maven.org/maven2"
      version_policy: "release"   # release | snapshot | mixed
      layout_policy: "strict"     # strict | permissive
```

---

## 💡 Special Format Notes

| Format | Special Settings |
| :--- | :--- |
| **Docker** | `connector: path` or `port`; Groups only support `path`. |
| **APT** | Requires `distribution` (e.g., `jammy`); Groups are not supported. |
| **Maven** | Requires `version_policy` and `layout_policy`. |
| **Yum** | Supports `repodata_depth` and `deploy_policy`. |
| **NuGet** | Supports `feed_version` (V2 or V3). |
| **Conan** | Supports `forge_url`. |
| **Terraform** | Supports `package_type` (MODULE or PROVIDER). |
| **Alpine** | Requires `signing_keypair` and `signing_passphrase` for Proxy/Hosted. |
| **Git LFS** | **Hosted only** (Proxy/Group are not supported by Nexus). |

---

## 🧪 Troubleshooting

### 1. Error: "Blob store 'X' not found"
- **Cause:** The specified blob store does not exist in Nexus.
- **Solution:** Create the blob store first or correct the name in your YAML file.

### 2. Error: "Unsupported repository type"
- **Cause:** The selected type (Hosted/Proxy/Group) is not supported for that format.
- **Solution:** Use a supported type (e.g., Conda only supports Proxy).

### 3. Docker Path-Based Routing not showing in UI
- **Solution:** The tool automatically sends `subdomain: null`. Ensure your Nexus `Base URL` is correctly configured in the Nexus Admin UI.

### 4. 404 Errors for Ansible or Git LFS
- **Solution:** These formats may not be supported in your Nexus edition (Community vs. Pro). The modules are designed to log a Warning and skip them gracefully without failing the entire run.

### 5. Config File Conflicts
- If the `nexus` key appears in multiple files, the **last file** (alphabetically) takes precedence. To avoid confusion, keep `nexus` in only one file (e.g., `00-nexus.yml`).

---

## 🔐 Security

- `config.d/` contains **tracked** example YAML files. `.gitignore` cannot protect
  an already-tracked file; never add real passwords, tokens, or private company
  URLs to these files. Use an external `--config-dir` for private configuration.
- `.env` and `.env.*` are ignored, except `.env.example`. Real environment
  files must be protected by file permissions and must not be committed.
- `NEXUS_USERNAME` and `NEXUS_PASSWORD` override the matching YAML fields.
  Environment variables are not a secret manager; prefer CI secret injection
  in automation. Credentials are masked in CLI log output when they appear in
  messages, including exception text, but this is not a substitute for keeping
  secrets out of source control and other tooling logs.
- If any real secret was committed previously, revoke or rotate it. Adding
  `.gitignore` or switching to environment variables does not erase Git history.

---

## 🤝 Contributing

Contributions are welcome! To add a new format:

1. Create a new file in `modules/` (e.g., `myformat.py`).
2. Implement the `create_repository(session, base_url, repo)` function.
3. Add the format name to the `FORMAT_MODULE_MAP` in `main.py`.
4. Create a sample config file in `config.d/` for testing.

Please follow the existing code style and include appropriate docstrings.

---

## 📄 License

This project is licensed under the **MIT License**. See the [LICENSE](LICENSE) file for details.

---

## 🌟 Credits

- **Sonatype** for Nexus Repository Manager.
- The Open Source community for `requests` and `PyYAML`.

---

## 📚 Topics

```
nexus nexus3 devops infrastructure-as-code python automation repository-manager iac
```

---

**❤️ Built with love for the DevOps community**
