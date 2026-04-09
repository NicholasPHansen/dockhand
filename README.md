# dockhand

A CLI tool for managing Docker containers on remote machines. Build, run, and manage Docker containers with a single command from your local machine.

## Features

- **Remote Docker Management**: Build and run Docker containers on a remote machine via SSH
- **File Syncing**: Automatically sync your local code to the remote before building
- **Volume Management**: Mount local directories into containers and download files back
- **Container History**: Track all container runs with full configuration snapshots
- **Quick Resubmit**: Easily rerun previous containers with the same or different parameters

## Installation

**From source with uv (recommended):**

uv provides fast, reliable dependency resolution and lock file management. [Install uv](https://docs.astral.sh/uv/):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then clone and sync:

```bash
git clone https://github.com/YOUR_USERNAME/dockhand.git
cd dockhand
uv sync
uv run dockhand --help
```

**Or with pip:**

```bash
pip install dockhand
```

## Usage

All commands work with the same `.dtu_hpc.json` configuration file format. See [Configuration](#configuration) below.

### Available Commands

- **submit**: Build the image and run a container with the given command(s)
- **run**: Run a container from an already-built image (skip build step)
- **install**: Build the Docker image without running it
- **logs**: Show logs from a container (defaults to last run)
- **stop**: Stop a running container (defaults to last run)
- **remove**: Remove container(s) from Docker (defaults to last run)
- **jobs**: List running containers (`docker ps`)
- **history**: Show history of all past Docker runs
- **volumes**: List files in docker-mounted volumes
- **download**: Download a file from a docker volume
- **resubmit**: Resubmit a previous Docker run with optional overrides

### Examples

```bash
# Build image and run a container
uv run dockhand submit --gpus all 'python train.py --epochs 10'

# Run a container from an already-built image
uv run dockhand run 'python train.py --epochs 20'

# Build image without running
uv run dockhand install --dockerfile Dockerfile.prod

# Check logs from the last container
uv run dockhand logs --n 50

# Stop the last running container
uv run dockhand stop

# Remove the last container and from history
uv run dockhand remove --from-history

# See all past runs
uv run dockhand history

# Download results
uv run dockhand download results/model.pth

# Resubmit the latest container with different GPUs
uv run dockhand resubmit --gpus '2'
```

**Note:** If you've installed dockhand globally, you can omit `uv run`.


## Configuration

Create a `.dtu_hpc.json` file in your project root with Docker and SSH configuration. All options in the configuration are optional.

### Minimal Configuration

```json
{
    "docker": {
        "dockerfile": "Dockerfile",
        "imagename": "my-image"
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
    }
}
```

Default hostname is `login1.hpc.dtu.dk`.

### Docker Configuration

```json
{
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
    }
}
```

- **dockerfile**: Path to the Dockerfile (required)
- **imagename**: Docker image name (required)
- **volumes**: List of volume mounts (required but can be empty list)
- **ports**: Port mappings (optional)
- **gpus**: GPU configuration for `docker run` (optional)
- **sync**: Whether to rsync local code before building (default: true)
- **workdir**: Working directory in container for path resolution (default: /)

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
uv run dockhand --profile dev submit 'python train.py'
uv run dockhand --profile prod submit 'python train.py'
```

### Complete Example

```json
{
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
        "sync": true,
        "workdir": "/app"
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

1. **Build** (`submit`/`install`): Optionally syncs local code via rsync, then runs `docker build` on the remote
2. **Run** (`submit`/`run`): Executes `docker run` with volumes, GPU flags, and port mappings
3. **History**: Stores container IDs and configurations in `.dtu_docker_history.json`
4. **Resubmit**: Looks up a previous run in history and re-runs with optional overrides
5. **Download**: Maps workdir-relative paths to host paths and uses rsync to download files

## Local vs Remote

- **On a remote machine with SSH**: Commands run via SSH (default)
- **On the Docker host directly**: Commands run locally (detected automatically)

## Requirements

- Python 3.10+
- git (for repo detection and branch tracking)
- SSH access to the remote machine (for remote docker host)
- Docker installed on the remote machine

## License

MIT
