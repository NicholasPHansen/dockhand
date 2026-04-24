# Dockhand

![](media/Gemini_Generated_Image_i700fvi700fvi700.png)

A CLI tool for managing Docker containers on remote machines. Build, run, and manage Docker containers with a single command from your local machine.

**Why this project?**

Managing Docker workloads across multiple machines is painful: keeping code in sync, remembering which version runs where, handling build/run/debug cycles remotely.

`dockhand` solves this by letting you manage everything from your laptop — code syncs automatically, builds happen on the remote, and results can be downloaded back. No more juggling multiple git repos or SSH sessions.

This project is *heavily* inspired by the awesome work from @ChrisFugl's [DTU-HPC-CLI](https://github.com/ChrisFugl/DTU-HPC-CLI).

## Features

- **Fast Iteration**: Code is mounted into the container at runtime — no rebuild needed when your code changes
- **Job Queue**: All workloads are submitted through [task spooler](https://viric.name/soft/ts/) so jobs run in order without competing for resources
- **Slot Reservations**: Declare how many CPU slots a job needs so heavy jobs don't block each other
- **Remote Docker Management**: Build and run Docker containers on a remote machine via SSH
- **Local or Remote**: Automatically detect localhost vs remote, or explicitly configure
- **Port Forwarding**: Establish SSH tunnels to access container ports locally
- **File Syncing**: Automatically sync your local code to the remote before running
- **Volume Management**: Mount data directories into containers and download results back
- **Stable Job IDs**: Local job IDs increment independently of the host, so IDs are unambiguous across machines
- **Quick Resubmit**: Easily rerun previous jobs with the same or different parameters

## Requirements

### Local machine

- Python 3.10+
- [git](https://git-scm.com/) — used for branch tracking and code sync

### Docker host (remote or local)

- [Docker](https://docs.docker.com/engine/install/) — container runtime
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) (`nvidia-docker`) — required only if using GPUs (`--gpus`)
- [task spooler (`tsp`)](https://viric.name/soft/ts/) — job queue daemon

Installing task spooler on Ubuntu/Debian:

```bash
sudo apt-get install task-spooler
```

On other systems the binary may be called `ts` instead of `tsp` — check your package manager.

**Configuring the total slot count** (optional, recommended for multi-user setups):

```bash
# Set the number of available slots to match CPU cores (run once on the host)
tsp -S 16
```

Jobs default to 1 slot each. Use `--slots` to reserve more (see [Slot Reservations](#slot-reservations)).

## Installation

**From source with uv (recommended):**

[Install uv](https://docs.astral.sh/uv/):

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

All commands work with the same `.dockhand.json` configuration file. See [Configuration](#configuration) below.

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

All commands that accept a job ID default to the most recent job if no ID is given.

### Typical workflow

```bash
# 1. Build the image once (or when dependencies change)
dockhand install

# 2. Iterate freely — submit syncs code and queues a run, no rebuild needed
dockhand submit 'python train.py --epochs 10'
dockhand submit 'python train.py --epochs 10'  # code changed? just submit again
```

### Examples

```bash
# Sync code and queue a run
dockhand submit 'python train.py --epochs 10'

# Reserve 4 CPU slots for a parallel job
dockhand submit --slots 4 'python train.py --workers 4'

# Queue a run with GPUs and port mappings
dockhand submit --gpus all -p 6006:6006 'python train.py'

# Queue a run without syncing (code already up to date)
dockhand submit --no-sync 'python train.py'

# Queue a run from an already-built image, skip sync
dockhand run 'python train.py --epochs 20'

# Build image (run once, or when dependencies change)
dockhand install
# Show full build output
dockhand install -v
# Build a specific Dockerfile
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

# Browse mounted volumes as a tree
dockhand volumes --depth 2

# Download results
dockhand download results/model.pth

# Resubmit the latest job with different GPUs
dockhand resubmit --gpus 2
```

**Note:** If you've installed dockhand globally, you can omit `uv run`.

## Slot Reservations

When multiple users share a Docker host, jobs may need different amounts of CPU resources. The `--slots` option maps to `tsp -N <n>`, which tells task spooler how many of the host's total slots a job should consume before it is allowed to start.

```bash
# Lightweight job — uses 1 slot (default)
dockhand run 'python eval.py'

# Parallel job — blocks 8 slots while running
dockhand run --slots 8 'python train.py --workers 8'
```

The total number of slots available on the host is set with `tsp -S <n>` (run once by the system admin). A job only starts when enough free slots are available, so heavy jobs naturally queue behind each other without manual coordination.

The default slot count can also be set in `.dockhand.json` so it applies to every submission without needing the flag:

```json
{
    "docker": {
        "slots": 4
    }
}
```

## Volumes

The `volumes` command lists the container filesystem as a unified tree rooted at `containerworkdir`. It searches the code mount (project root → `containerworkdir`) and all configured data volumes on the host directly — no running container required. Files appear at their container paths.

```bash
# Show container filesystem (default depth: 5 levels)
dockhand volumes

# Expand to a specific depth; folders at the limit show as collapsed with ...
dockhand volumes --depth 3

# Show filesystem for a specific past job
dockhand volumes 42

# Same via download --list
dockhand download --list --depth 2
```

The `download` command resolves any workdir-relative path (as shown by `volumes`) back to its host location and downloads it via rsync. Directory downloads preserve the full path structure locally.

```bash
# Download a file
dockhand download results/model.pth

# Download a directory (trailing slash) — files land in reports/figures/ locally
dockhand download reports/figures/
```

## Configuration

Create a `.dockhand.json` file in your project root.

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

To run Docker commands on a remote machine:

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

- No `ssh` config, or hostname resolves to `127.0.0.1` → runs locally
- Otherwise → connects via SSH

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
        "slots": 1,
        "containerworkdir": "/"
    }
}
```

**Top-level options:**

| Option | Description | Default |
|--------|-------------|---------|
| `sync` | Rsync local code to remote before building | `true` |

**Docker sub-config options:**

| Option | Description | Default |
|--------|-------------|---------|
| `dockerfile` | Path to the Dockerfile | required |
| `imagename` | Docker image name | required |
| `volumes` | List of volume mounts | required |
| `ports` | Port mappings | — |
| `gpus` | GPU flag passed to `docker run --gpus` | — |
| `slots` | Queue slots to reserve per job | `1` |
| `containerworkdir` | Path inside the container where the project is mounted and commands run from | `/` |

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
                "slots": 8,
                "dockerfile": "Dockerfile.prod"
            }
        },
        "dev": {
            "docker": {
                "gpus": "1",
                "slots": 2,
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
        "slots": 4,
        "containerworkdir": "/app"
    },
    "remote_path": "/home/myuser/projects/my-app",
    "profiles": {
        "quick": {
            "docker": {
                "gpus": "1",
                "slots": 1
            }
        }
    }
}
```

## How It Works

1. **Build** (`install`): Optionally syncs local code via rsync, then runs `docker build` on the host. Pass `-v` to stream build output; default shows a spinner only. Only needed when dependencies or the Dockerfile change.
2. **Submit** (`submit`/`run`): Optionally syncs code to the remote, then submits a `docker run` command to task spooler (`tsp`). The project directory is automatically mounted into the container at `containerworkdir`, so the running container always uses your latest code without a rebuild.
3. **Queue**: tsp runs jobs one at a time in submission order. Jobs with `--slots N` only start when N free slots are available.
4. **Job IDs**: Each submission gets a local job ID (stable, auto-incrementing) stored alongside the host and tsp job number. The local ID is what all commands accept.
5. **Logs** (`logs`): Reads directly from the tsp output file. Use `--follow`/`-f` to stream a running job live, `--n N` for the last N lines.
6. **Port Forwarding** (`tunnel`): Establishes SSH local port forwards for container ports.
7. **Download**: Maps containerworkdir-relative paths to host paths and uses rsync to fetch files.

## License

MIT
