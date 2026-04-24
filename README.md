# Dockhand

![](media/Gemini_Generated_Image_i700fvi700fvi700.png)

A CLI tool for managing Docker containers on remote machines. Build, run, and manage Docker containers with a single command from your local machine.

**Why this project?**

Managing Docker workloads across multiple machines is painful: keeping code in sync, remembering which version runs where, handling build/run/debug cycles remotely.

`dockhand` solves this by letting you manage everything from your laptop - code syncs automatically, builds happen on the remote, and you track history locally, and after running you can download results back. No more juggling multiple git repos or SSH sessions.

This project is *heavily* inspired by the awesome work from @ChrisFugl's [DTU-HPC-CLI](https://github.com/ChrisFugl/DTU-HPC-CLI).

## Features

- **Job Queue**: Submit workloads to a [task spooler](https://viric.name/soft/ts/) queue so jobs run in order without stepping on each other
- **Remote Docker Management**: Build and run Docker containers on a remote machine via SSH
- **Local or Remote**: Automatically detect localhost vs remote, or explicitly configure
- **Job Queue**: Optional [task spooler](https://viric.name/soft/ts/) integration — submit jobs to a shared queue so they run in order across multiple users
- **Port Forwarding**: Establish SSH tunnels to access container ports locally
- **File Syncing**: Automatically sync your local code to the remote before building
- **Volume Management**: Mount local directories into containers and download files back
- **Job History**: Track all runs with local job IDs that are stable across hosts
- **Quick Resubmit**: Easily rerun previous jobs with the same or different parameters

## Requirements

### Local machine

- Python 3.10+
- [git](https://git-scm.com/) — used for branch tracking and code sync

### Docker host (remote or local)

- [Docker](https://docs.docker.com/engine/install/) — container runtime
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) (`nvidia-docker`) — required only if using GPUs (`--gpus`)
- [task spooler (`tsp`)](https://viric.name/soft/ts/) — job queue daemon; jobs submitted via `dockhand` are queued through `tsp`

Installing task spooler on Ubuntu/Debian:

```bash
sudo apt-get install task-spooler
```

On other systems the binary may be called `ts` instead of `tsp` — check your package manager.

## Installation

**From source with uv (recommended):**

uv provides fast, reliable dependency resolution and lock file management. [Install uv](https://docs.astral.sh/uv/):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then clone and sync:

```bash
git clone https://github.com/nicholasphansen/dockhand.git
cd dockhand
uv sync
uv run dockhand --help
```

**Or with pip:**

```bash
pip install dockhand
```

## Usage

All commands work with the same `.dockhand.json` configuration file format. See [Configuration](#configuration) below.

### Available Commands

| Command | Description |
|---------|-------------|
| `submit` | Build the image and queue a container run |
| `run` | Queue a container run from an already-built image |
| `install` | Build the Docker image without running it |
| `jobs` | List active (running/queued) jobs — use `--all` for finished jobs too |
| `logs` | Show logs from a job — use `--follow`/`-f` to stream live |
| `stop` | Stop a **running** job |
| `remove` | Remove a **queued** job before it starts |
| `urgent` | Promote a queued job to the front of the queue |
| `history` | Show history of all past runs |
| `volumes` | List the full container filesystem as a tree |
| `download` | Download a file from a docker volume |
| `resubmit` | Resubmit a previous job with optional overrides |
| `tunnel` | Forward container ports to localhost via SSH tunnel |

All commands that take a job ID default to the most recent job if no ID is provided.

### Examples

```bash
# Build image and queue a run
dockhand submit 'python train.py --epochs 10'

# Queue a run with GPUs and port mappings
dockhand submit --gpus all -p 6006:6006 'python train.py'

# Queue a run from an already-built image
dockhand run 'python train.py --epochs 20'

# Build image only
dockhand install --dockerfile Dockerfile.prod

# Check active jobs
dockhand jobs

# Check all jobs including finished
dockhand jobs --all

# Stream logs from the last job
dockhand logs --follow

# Show the last 50 lines from job #3
dockhand logs 3 --n 50

# Stop the last running job
dockhand stop

# Remove a queued job before it starts
dockhand remove 4

# Promote job #5 to the front of the queue
dockhand urgent 5

# Forward container ports to localhost
dockhand tunnel

# See all past runs
dockhand history

# Browse mounted volumes
dockhand volumes --depth 2

# Browse the full container filesystem as a tree
uv run dockhand volumes
uv run dockhand volumes --depth 3

# Download results
dockhand download results/model.pth

# Resubmit the latest job with different GPUs
dockhand resubmit --gpus 2
```

**Note:** If you've installed dockhand globally, you can omit `uv run`.

## Job Queue

When multiple people share a Docker host, dockhand can queue jobs through [task spooler](https://viric.name/soft/ts/) (`tsp`) so they run in order rather than competing for resources.

### Setup

Install `tsp` on the Docker host (once):

```bash
# Debian/Ubuntu
sudo apt install task-spooler

# macOS
brew install task-spooler
```

Then enable the queue in `.dockhand.json`:

```json
{
    "queue": {
        "enabled": true
    }
}
```

### Queue Commands

```bash
# Submit a job — returns a job ID immediately
uv run dockhand submit 'python train.py'
# Job queued with ID 3

# Submit with high priority (moves to front of queue)
uv run dockhand submit --urgent 'python eval.py'

# List all jobs in the queue
uv run dockhand jobs

# Promote an already-queued job to the front
uv run dockhand urgent 3

# Check logs for job 3
uv run dockhand logs 3

# Stop a running job or cancel a queued one
uv run dockhand stop 3

# Remove a pending job from the queue
uv run dockhand remove 3

# Resubmit a previous job with different parameters
uv run dockhand resubmit 3 --gpus 2
```

When queue is disabled, all commands fall back to their original behaviour (direct `docker` calls, container IDs).

## Volumes

The `volumes` command spins up a temporary container (`docker run --rm`) with your configured mounts and lists the full filesystem as a tree — including files baked into the image, not just mounted paths.

```bash
# Show full container filesystem
uv run dockhand volumes

# Limit depth
uv run dockhand volumes --depth 3

# Show filesystem for a specific job or container
uv run dockhand volumes 42           # by job ID (queue mode)
uv run dockhand volumes abc123def456 # by container ID

# Same via download --list
uv run dockhand download --list --depth 2
```

## Configuration

Create a `.dockhand.json` file in your project root with Docker and SSH configuration.

### Minimal Configuration

```json
{
    "docker": {
        "dockerfile": "Dockerfile",
        "imagename": "my-image",
        "volumes": []
    }
}
```

### SSH Configuration

To run Docker commands on a remote machine, configure SSH:

```json
{
    "ssh": {
        "user": "your_username",
        "identityfile": "/path/to/private/key",
        "hostname": "remote.example.com"
    },
    "docker": { "..." }
}
```

Hostname detection:

- If `ssh` config is missing → uses LocalClient
- If `ssh.hostname` resolves to localhost or `127.0.0.1` → uses LocalClient
- Otherwise → uses SSHClient

### Docker Configuration

```json
{
    "sync": true,
    "ssh": { "..." },
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
        "containerworkdir": "/"
    },
    "queue": {
        "enabled": false
    }
}
```

**Top-level options:**

- **sync**: Whether to rsync local code before building (default: true)
- **queue.enabled**: Enable task spooler queue integration (default: false)

**Docker sub-config options:**

- **dockerfile**: Path to the Dockerfile (required)
- **imagename**: Docker image name (required)
- **volumes**: List of volume mounts (required but can be empty list)
- **ports**: Port mappings (optional)
- **gpus**: GPU configuration passed to `docker run --gpus` (optional)
- **containerworkdir**: Working directory in container for path resolution (default: /)

### Profiles

Use profiles to switch between different configurations:

```json
{
    "docker": {
        "dockerfile": "Dockerfile",
        "imagename": "my-image"
    },
    "profiles": {
        "prod": {
            "docker": {
                "gpus": "all",
                "dockerfile": "Dockerfile.prod"
            }
        },
        "dev": {
            "docker": {
                "gpus": "1",
                "dockerfile": "Dockerfile.dev"
            }
        }
    }
}
```

```bash
dockhand --profile dev submit 'python train.py'
dockhand --profile prod submit 'python train.py'
```

### Complete Example

```json
{
    "sync": true,
    "ssh": {
        "user": "myuser",
        "identityfile": "~/.ssh/id_rsa",
        "hostname": "gpu-server.example.com"
    },
    "docker": {
        "dockerfile": "Dockerfile",
        "imagename": "my-training-app",
        "volumes": [
            {
                "hostpath": "/local/data",
                "containerpath": "/data",
                "permissions": "rw"
            },
            {
                "hostpath": "/local/models",
                "containerpath": "/models",
                "permissions": "rw"
            }
        ],
        "ports": ["6006:6006"],
        "gpus": "all",
        "containerworkdir": "/app"
    },
    "queue": {
        "enabled": true
    },
    "remote_path": "/home/myuser/projects/my-app",
    "profiles": {
        "quick": {
            "docker": {
                "gpus": "1"
            }
        }
    }
}
```

## How It Works

1. **Build** (`submit`/`install`): Optionally syncs local code via rsync, then runs `docker build` on the host
2. **Queue** (`submit`/`run`): Submits a `docker run` command to task spooler (`tsp`), which runs jobs one at a time in order
3. **Job IDs**: Each submission gets a local job ID (stable, incrementing) alongside the tsp job number — the local ID is what you use in all commands
4. **Logs** (`logs`): Reads from the tsp output file; use `--follow` to stream a running job live
5. **Port Forwarding** (`tunnel`): Establishes SSH local port forwards for container ports
6. **Download**: Maps containerworkdir-relative paths to host paths and uses rsync to fetch files

## License

MIT
