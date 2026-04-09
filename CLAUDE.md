# CLAUDE.md — dockhand Development Guide

## Project Overview

**dockhand** is a standalone CLI tool extracted from DTU-HPC-CLI for managing Docker containers on remote machines (or locally). It provides a unified interface to build, run, manage, and monitor Docker containers via SSH or locally.

**Key philosophy:** Simple, flat command structure with sensible SSH defaults. One `.dtu_hpc.json` config file works everywhere.

## Commands

**Prerequisites:**
- Install [uv](https://docs.astral.sh/uv/): `curl -LsSf https://astral.sh/uv/install.sh | sh`

**Installation & Setup:**
```bash
# Install dependencies and create lock file
uv sync

# Update lock file with latest versions (if needed)
uv lock --upgrade
```

**Run the CLI locally:**
```bash
uv run dockhand --help
```

**Lint:**
```bash
uv run ruff check .
```

**Format:**
```bash
uv run ruff format .
```

**Auto-fix lint issues:**
```bash
uv run ruff check --fix .
```

## Architecture

### Entry Point
`dockhand/__init__.py` — Defines the Typer CLI app. All 11 commands are at the top level (flat structure, not nested under a `docker` sub-group). Each command delegates to an `execute_*` function in `docker.py`.

**Commands at top level:**
- `dockhand submit` — build image + run container
- `dockhand run` — run container from already-built image
- `dockhand install` — build image only
- `dockhand logs`, `stop`, `remove`, `jobs`, `history`, `volumes`, `download`, `resubmit`

All commands validate config inline with `cli_config.check_docker()`.

### Configuration System
`dockhand/config.py` — The `CLIConfig` class is loaded at module import time (`cli_config = CLIConfig.load()`) by walking up the directory tree to find `.dtu_hpc.json`. Contains:
- `SSHConfig` — hostname, user, identity file for SSH connections
- `DockerConfig` — dockerfile, imagename, volumes, ports, gpus, sync, workdir
- `CLIConfig` — top-level config holder

Config file: `.dtu_hpc.json` in the project root. History file: `.dtu_docker_history.json` (same location by default).

### Client Abstraction
`dockhand/client/` — `Client` (abstract base) has two implementations:
- `SSHClient` — connects via Fabric/Paramiko over SSH
- `LocalClient` — runs commands locally (used when already on docker host, detected by checking if `bstat` is available)

`get_client()` auto-detects the environment.

### Key Modules
- `docker.py` — All docker command implementations. Handles building, running, stopping, removing containers, plus history tracking and file downloads.
- `sync.py` — Uses `rsync` over SSH to copy local files to `remote_path`, respecting `.gitignore`.
- `config.py` — Configuration loading and validation.
- `error.py` — Centralized error reporting with rich panels.
- `constants.py` — Config filenames.

### Docker History
Stores container runs in `.dtu_docker_history.json` as JSON. Each entry contains:
```json
{
  "config": {
    "dockerfile": "...",
    "imagename": "...",
    "gpus": "...",
    "volumes": [...],
    "commands": [...],
    "branch": "..."  // optional, detected from git
  },
  "container_id": "abc123def456",  // 12-char short ID
  "timestamp": 1234567890.123
}
```

Used by `resubmit` (look up a previous run and re-run with overrides), `logs`, `stop`, `remove` (default to latest if no ID given).

### Design Patterns

**DockerDefault factory:**
In `__init__.py`, `DockerDefault` is a callable factory that pulls defaults from `cli_config.docker` at call time. Enables Typer's `default_factory` to respect active profiles.

**Profile support:**
`cli_config.load_profile(name)` loads overrides from `.dtu_hpc.json` profiles section. All config classes support `validate()` for safe merging.

**Command structure:**
Each command:
1. Calls `cli_config.check_docker()` to validate config
2. Calls an `execute_*` function from `docker.py`
3. Passes `cli_config.docker` as the config argument

## Differences from DTU-HPC-CLI

- **Flat commands** — no `docker` sub-group. Commands are top-level.
- **No HPC support** — SubmitConfig, InstallConfig, and all LSF/job submission code removed
- **Smaller footprint** — ~20KB vs 50KB, fewer dependencies
- **Docker-focused** — all UI/UX optimized for docker workflows

## Key Files and Their Responsibilities

| File | Purpose |
|------|---------|
| `__init__.py` | CLI app definition, command routing, config defaults |
| `docker.py` | All docker command implementations |
| `config.py` | Config loading, validation, profile support |
| `client/__init__.py` | Auto-detect and return appropriate client |
| `client/base.py` | Abstract Client interface |
| `client/local.py` | Local command execution |
| `client/ssh.py` | Remote execution via SSH (Fabric/Paramiko) |
| `sync.py` | rsync-based code synchronization |
| `error.py` | Error reporting |
| `constants.py` | Config file names |

## Configuration Format

`.dtu_hpc.json` in project root:

```json
{
  "ssh": {
    "user": "your_username",
    "identityfile": "~/.ssh/id_rsa",
    "hostname": "remote.example.com"
  },
  "docker": {
    "dockerfile": "Dockerfile",
    "imagename": "my-image",
    "volumes": [
      {
        "hostpath": "/local/data",
        "containerpath": "/data",
        "permissions": "rw"
      }
    ],
    "ports": ["8080:80"],
    "gpus": "all",
    "sync": true,
    "workdir": "/"
  },
  "remote_path": "~/my-project",
  "modules": ["python3/3.11"],
  "profiles": {
    "dev": {
      "docker": {
        "gpus": "1",
        "dockerfile": "Dockerfile.dev"
      }
    }
  }
}
```

All options are optional except `dockerfile`, `imagename`, and `volumes` within docker config.

## Common Workflows

**First time setting up:**
1. Create `.dtu_hpc.json` with `docker` and `ssh` sections
2. Run `dockhand install` to build the image
3. Run `dockhand submit 'command'` to run a container

**Development iteration:**
```bash
uv run dockhand submit --gpus 1 'python train.py'  # Build + run with 1 GPU
uv run dockhand logs --n 50                        # Check last 50 log lines
uv run dockhand resubmit --gpus 2                  # Re-run with 2 GPUs
uv run dockhand download results/model.pth         # Get results back
```

**Quick rebuild:**
```bash
uv run dockhand install --dockerfile Dockerfile.dev  # Rebuild only
uv run dockhand run 'bash'                           # Run interactively
```

**Using profiles:**
```bash
uv run dockhand --profile dev submit 'python train.py'   # Use dev profile
uv run dockhand --profile prod install                   # Build prod image
```

## Testing & Validation

No automated tests yet. Manual validation:
```bash
uv run dockhand --help         # Check CLI structure
uv run dockhand submit --help  # Check submit options
uv run ruff check .            # Lint
uv run ruff format --check .   # Format check
```

## Important Design Decisions

1. **Flat commands** — No `docker` sub-group. Simpler for a docker-only tool.
2. **SSH by default** — Assumes docker host is remote. Auto-detects local with `bstat`.
3. **Reuse DTU-HPC-CLI config format** — Compatibility with existing `.dtu_hpc.json` files.
4. **History in JSON** — Simple, human-readable, easily editable.
5. **Profile support** — Same as DTU-HPC-CLI; allows per-project config variants.
6. **Minimal dependencies** — Only typer, fabric, paramiko, gitpython (not uuid, which DTU-HPC-CLI had).

## Extraction History

- **Source:** DTU-HPC-CLI (github.com/ChrisFugl/DTU-HPC-CLI)
- **Extracted:** 2026-04-09
- **Changes:**
  - Removed: SubmitConfig, InstallConfig, types.py, all HPC modules
  - Modified: config.py (trimmed), __init__.py (flat commands)
  - Unchanged: docker.py, sync.py, error.py, client/*, constants.py

## Future Enhancements

Potential improvements specific to dockhand:
- Docker Compose support (`dockhand compose up`)
- Kubernetes pod management
- Local-only mode (drop SSH dependency for pure local docker)
- Config auto-generation wizard
- Container registry integration (Docker Hub, ECR, GCR)
- Multi-container orchestration helpers
- Better volume inspection (list files, sizes, modification times)

## Contributing

When working on dockhand:
1. Keep the flat command structure — don't re-introduce `docker` sub-groups
2. Maintain `.dtu_hpc.json` compatibility
3. Test manually with `uv run dockhand <command> --help` and actual docker operations
4. Follow ruff lint/format rules (use `uv run ruff check . && uv run ruff format .`)
5. Document new features in README.md and CLAUDE.md
6. Update EXTRACTION_NOTES.md if architecture changes

## Maintenance

dockhand is maintained independently from DTU-HPC-CLI. Version bumps and releases are separate. If you need HPC support, use the original DTU-HPC-CLI package.
