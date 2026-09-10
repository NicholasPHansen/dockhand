# CLAUDE.md — dockhand Development Guide

## Project Overview

**dockhand** is a standalone CLI tool, originally extracted from DTU-HPC-CLI, for managing Docker containers on remote machines (or locally). It provides a unified interface to build, run, queue, manage, and monitor Docker containers via SSH or locally.

**Key philosophy:** Simple, flat command structure with sensible SSH defaults. One `.dockhand.json` config file works everywhere.

Since extraction, dockhand has grown features DTU-HPC-CLI never had: a task-spooler-based job queue, a mount-vs-bake code delivery mode, a direct (non-queued) run transport, and baked-image pruning. See [Relationship to DTU-HPC-CLI](#relationship-to-dtu-hpc-cli).

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
`dockhand/__init__.py` — Defines the Typer CLI app. All commands are at the top level (flat structure, not nested under a `docker` sub-group). Each command validates config with `cli_config.check_docker()` and delegates to an `execute_*` function in the relevant module below.

**Commands at top level:**
- `dockhand submit` — sync code, then queue/run a container
- `dockhand run` — queue/run from an already-built image, no sync
- `dockhand install` — build the image only
- `dockhand logs`, `stop`, `remove`, `jobs`, `urgent`, `prune` — job/queue lifecycle (`manage.py` + `queue.py`)
- `dockhand history` — show past runs
- `dockhand volumes`, `download` — inspect and pull files from mounted volumes
- `dockhand resubmit` — rerun a past job with optional overrides
- `dockhand tunnel` — SSH-forward container ports to localhost

### Configuration System
`dockhand/config.py` — The `CLIConfig` class is loaded at module import time (`cli_config = CLIConfig.load()`) by walking up the directory tree to find `.dockhand.json`. Contains:
- `SSHConfig` — hostname, user, identity file for SSH connections
- `DockerConfig` — dockerfile, imagename, volumes, ports, gpus, containerworkdir, preserve_paths, code_delivery
- `QueueConfig` — enabled, tool, slots (task-spooler queue settings)
- `CLIConfig` — top-level config holder (ssh, docker, queue, sync, remote_path, profiles)

Config file: `.dockhand.json` in the project root (must also contain a `.git` — `CLIConfig.load()` errors if no git repo is found). History file: `.dockhand_history.json` (same location by default, overridable via `history_path`).

### Client Abstraction
`dockhand/client/` — `Client` (abstract base) has two implementations:
- `SSHClient` — connects via Fabric/Paramiko over SSH
- `LocalClient` — runs commands locally

`get_client()` picks `LocalClient` when `cli_config.ssh` is unset or the configured hostname resolves to loopback, otherwise `SSHClient`. `get_client_for_host(hostname)` does the same but for an explicit hostname (used by `logs`/`stop`/`remove`, which read the host from the job's history entry rather than current config).

### Key Modules
- `submit.py` — Builds the `docker run` command (code mount vs. data volumes vs. GPU/port flags), resolves code delivery, and hands off to a transport to start the job.
- `build.py` — Runs `docker build` on the client (optionally syncing first).
- `manage.py` — Job lifecycle: `logs`, `stop`, `remove`, `jobs` (`execute_stats`), and `prune` (removes baked images no longer referenced by an active job).
- `resubmit.py` — Looks up a history entry and re-invokes `execute_submit` with overrides; pins to the original baked image when applicable.
- `queue.py` — Task spooler (`tsp`) integration: submit/list/promote/remove/kill, plus `ts -l` output parsing.
- `transport.py` — Abstracts "how a job runs": `TaskSpoolerTransport` (queue enabled) vs. `DockerTransport` (direct `docker run -d`). Both expose the same interface (`submit`, `list_jobs`, `logs`, `stop`, `remove`) so job-management commands don't care which backend created a job; the transport used is recorded per job in history.
- `tagging.py` — Resolves the image tag/ref for baked code delivery (content-addressed from git commit + dirty-state hash; unique per queued submit, reused for direct runs).
- `history.py` — Reads/writes `.dockhand_history.json`, reserves/looks up local job IDs.
- `volumes.py` — Lists the container filesystem as a tree (code mount + data volumes) and resolves a workdir-relative path back to its host path.
- `download.py` — Uses `volumes._resolve_to_host` + rsync to pull a file/directory from a volume.
- `tunnel.py` — SSH local port forwarding to container ports (via Fabric).
- `sync.py` — Uses `rsync` over SSH to copy local files to `remote_path`, respecting `.gitignore`; prompts to confirm when the worktree is dirty.
- `config.py` — Configuration loading and validation.
- `error.py` — Centralized error reporting with rich panels.
- `constants.py` — Config/history filenames.

> **Known inconsistency:** `tunnel.py` still looks up history entries by a `container_id` field (`entry["container_id"]`), but `history.py` no longer writes that field — entries are keyed by `local_id` with a transport `handle`. Passing an explicit `container_id` to `dockhand tunnel` will not resolve; only the no-argument (last job) path works reliably.

### Docker History
Stores container runs in `.dockhand_history.json` as JSON. Each entry contains:
```json
{
  "local_id": 7,
  "timestamp": 1234567890.123,
  "config": {
    "gpus": "all",
    "volumes": [...],
    "imagename": "my-image",
    "commands": ["python", "train.py"],
    "ports": ["6006:6006"],
    "image_ref": "my-image:abc123def456",  // present when built (baked delivery)
    "branch": "main"                        // optional, detected from git
  },
  "transport": "task_spooler",   // or "docker"
  "handle": 12,                  // tsp job id, or container name for direct runs
  "ts_job_id": 12,                // task_spooler transport only
  "host": "remote.example.com",   // or "localhost"
  "started_at": 1234567891.0,     // optional, set the first time `jobs` observes it running
  "ended_at": 1234567895.0        // optional, set the first time `jobs` observes it finished/failed/stopped
}
```

Used by `resubmit` (look up a previous run and re-run with overrides, pinning the original baked image when unchanged), `logs`, `stop`, `remove`, `jobs`, `urgent`, `prune` (default to latest if no ID given). Job-management commands dispatch to the transport recorded on the entry (`transport_for_entry`), so `logs`/`stop`/`remove` work the same regardless of whether a job went through the queue or ran directly.

`started_at`/`ended_at` aren't queried from tsp/docker (neither exposes exact start/end timestamps cheaply for both transports) — `jobs` and `logs` each stamp them lazily the first time they happen to observe a job in the running/terminal state, so a job never checked on while running will show no start time once it finishes. `dockhand jobs` displays these as Started/Ended (relative, e.g. `5m ago`) and Duration (elapsed while running, total once finished) columns; `dockhand logs` prints a one-line "running for Xm" / "finished in Xm" header before the log output.

### Design Patterns

**DockerDefault factory:**
In `__init__.py`, `DockerDefault` is a callable factory that pulls defaults from `cli_config.docker` at call time. Enables Typer's `default_factory` to respect active profiles.

**Transport abstraction:**
`get_transport()` in `transport.py` picks `TaskSpoolerTransport` or `DockerTransport` based on `cli_config.queue.enabled` at submit time. Every job-management command re-derives the correct transport per-job from the history entry (`transport_for_entry`) rather than from current config, so switching `queue.enabled` doesn't strand in-flight jobs from the other mode.

**Code delivery resolution:**
`DockerConfig.resolve_code_delivery(queue_enabled)` picks `mount` or `bake` when `code_delivery` isn't explicitly set: `bake` when the queue is enabled (avoids code drift while a job waits in queue), `mount` otherwise (zero-rebuild iteration). See README's [Code delivery](README.md#code-delivery-mount-vs-bake) section for the full rationale.

**Profile support:**
`cli_config.load_profile(name)` loads overrides from `.dockhand.json` profiles section (currently merges `history_path`, `remote_path`, `ssh`). All config classes support `validate()` for safe merging.

**Command structure:**
Each command:
1. Calls `cli_config.check_docker()` to validate config
2. Calls an `execute_*` function from the relevant module
3. Passes `cli_config.docker` (and often `cli_config.queue`) as config arguments

## Relationship to DTU-HPC-CLI

- **Flat commands** — no `docker` sub-group. Commands are top-level.
- **No HPC support** — SubmitConfig, InstallConfig, and all LSF/job submission code removed
- **Docker-focused** — all UI/UX optimized for docker workflows
- **Config-compatible in spirit, not in filename** — dockhand originally reused DTU-HPC-CLI's `.dtu_hpc.json`/`.dtu_docker_history.json` names; both have since been renamed to `.dockhand.json`/`.dockhand_history.json` (see `constants.py`). Old DTU-HPC-CLI config files need renaming (or a `history_path` override) to work with dockhand.
- **Diverged, not just trimmed** — dockhand has added its own features DTU-HPC-CLI doesn't have: a task-spooler queue (`queue.py`/`transport.py`), slot reservations, `mount`/`bake` code delivery (`tagging.py`), a direct-run transport for when the queue is off, `urgent`/`prune`/`tunnel` commands. Maintained independently; version/release cadence is separate from DTU-HPC-CLI.

## Key Files and Their Responsibilities

| File | Purpose |
|------|---------|
| `__init__.py` | CLI app definition, command routing, config defaults |
| `submit.py` | Builds the `docker run` command, resolves code delivery, submits via transport |
| `build.py` | `docker build` execution |
| `manage.py` | `logs`, `stop`, `remove`, `jobs`, `prune` |
| `resubmit.py` | Rerun a past job with overrides |
| `queue.py` | Task spooler (`tsp`) integration |
| `transport.py` | Task-spooler vs. direct-docker execution backends |
| `tagging.py` | Image tag resolution for baked code delivery |
| `history.py` | Read/write `.dockhand_history.json`, job ID allocation |
| `volumes.py` | Container filesystem tree, path resolution |
| `download.py` | rsync-based file download from volumes |
| `tunnel.py` | SSH port forwarding to container ports |
| `config.py` | Config loading, validation, profile support |
| `client/__init__.py` | Auto-detect and return appropriate client |
| `client/base.py` | Abstract Client interface |
| `client/local.py` | Local command execution |
| `client/ssh.py` | Remote execution via SSH (Fabric/Paramiko) |
| `sync.py` | rsync-based code synchronization |
| `error.py` | Error reporting |
| `constants.py` | Config/history file names |

## Configuration Format

`.dockhand.json` in project root (project root is also where `CLIConfig.load()` expects to find a `.git` directory):

```json
{
  "sync": true,
  "ssh": {
    "user": "your_username",
    "identityfile": "~/.ssh/id_rsa",
    "hostname": "remote.example.com"
  },
  "queue": {
    "enabled": true,
    "slots": 1
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
    "containerworkdir": "/",
    "preserve_paths": [".venv"],
    "code_delivery": null
  },
  "remote_path": "~/my-project",
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

All options are optional except `dockerfile`, `imagename`, and `volumes` within docker config. `queue.slots` may also be set as `docker.slots` for back-compat (deprecation warning printed). Full option tables and defaults are documented in README.md's [Configuration](README.md#configuration) section — keep both in sync when config shape changes.

## Common Workflows

**First time setting up:**
1. Create `.dockhand.json` with `docker` and `ssh` sections
2. Run `dockhand install` to build the image
3. Run `dockhand submit 'command'` to run a container

**Development iteration:**
```bash
uv run dockhand submit --gpus 1 'python train.py'  # Sync + queue/run with 1 GPU
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

**Queue management:**
```bash
uv run dockhand jobs                  # List active jobs
uv run dockhand urgent 5               # Promote job #5 to front of queue
uv run dockhand prune --dry-run        # Preview unused baked images before removing
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
2. **SSH by default** — Assumes docker host is remote. Auto-detects local by resolving the configured hostname to a loopback address.
3. **History in JSON** — Simple, human-readable, easily editable.
4. **Profile support** — Allows per-project config variants.
5. **Minimal dependencies** — typer, fabric, paramiko, gitpython, rich.
6. **Transport abstraction over queue state** — job-management commands read the transport from each job's own history entry rather than current `queue.enabled`, so toggling the queue mid-flight doesn't orphan existing jobs.
7. **Code-delivery default follows queue mode** — `bake` when queued (avoids code drift while waiting), `mount` when not (zero-rebuild iteration); explicit `code_delivery` overrides either way.

## Extraction History

- **Source:** DTU-HPC-CLI (github.com/ChrisFugl/DTU-HPC-CLI)
- **Extracted:** 2026-04-09
- **Initial changes:**
  - Removed: SubmitConfig, InstallConfig, types.py, all HPC modules
  - Modified: config.py (trimmed), __init__.py (flat commands)
  - Unchanged at the time: docker.py, sync.py, error.py, client/*, constants.py
- **Since extraction:** the original monolithic `docker.py` was split into `build.py`, `submit.py`, `manage.py`, `resubmit.py`, `history.py`, `download.py`, `volumes.py`, `tunnel.py`; `queue.py`, `transport.py`, and `tagging.py` were added for the task-spooler queue, transport abstraction, and baked code delivery. Config/history filenames moved from `.dtu_hpc.json`/`.dtu_docker_history.json` to `.dockhand.json`/`.dockhand_history.json`.

## Future Enhancements

Potential improvements specific to dockhand (volume inspection is already implemented — see `volumes.py`):
- Docker Compose support (`dockhand compose up`)
- Kubernetes pod management
- Local-only mode (drop SSH dependency for pure local docker)
- Config auto-generation wizard
- Container registry integration (Docker Hub, ECR, GCR)
- Multi-container orchestration helpers
- Fix `tunnel.py`'s stale `container_id` history lookup (see [Known inconsistency](#key-modules) above)

## Contributing

When working on dockhand:
1. Keep the flat command structure — don't re-introduce `docker` sub-groups
2. Maintain `.dockhand.json` compatibility
3. Test manually with `uv run dockhand <command> --help` and actual docker operations
4. Follow ruff lint/format rules (use `uv run ruff check . && uv run ruff format .`)
5. Document new features in README.md and CLAUDE.md
6. Update this file's Architecture section when modules are added, split, or renamed — it has drifted from actual code structure before

## Maintenance

dockhand is maintained independently from DTU-HPC-CLI. Version bumps and releases are separate. If you need HPC support, use the original DTU-HPC-CLI package.
