# Dockhand: Extracted from DTU-HPC-CLI

This standalone `dockhand` CLI was extracted from DTU-HPC-CLI on 2026-04-09 to provide a dedicated Docker management tool that can be maintained independently.

## What was extracted

### Full modules (unchanged except for import prefix updates)
- `docker.py` — all docker command implementations
- `sync.py` — SSH+rsync synchronization
- `error.py` — error reporting
- `constants.py` — config filenames
- `client/` — SSH and local client implementations

### Modified modules
- `config.py` — **trimmed** to remove `SubmitConfig` and `InstallConfig` classes (HPC-only)
  - Kept: `DockerConfig`, `DockerResubmitConfig`, `SSHConfig`, `CLIConfig`
  - Removed: types.py import, HPC-specific constants

- `__init__.py` — **rewritten** with flat command structure
  - Kept: all 11 docker commands
  - Removed: `docker_app` sub-group (now flat: `dockhand submit` instead of `dtu docker submit`)
  - Added: config validation in each command

### Dropped entirely
- `types.py` — only used by SubmitConfig (HPC-only)
- All HPC modules: `history.py`, `submit.py`, `install.py`, `jobs.py`, `remove.py`, `resubmit.py`, `run.py`, `start.py`, `stats.py`, `queues.py`, `download.py`, etc.

## Setup

### Install from source
```bash
cd dockhand
pip install -e .
```

### Install dependencies
```bash
pip install typer fabric paramiko gitpython
```

### Use with pyenv/poetry/uv
```bash
uv run dockhand --help
```

## Configuration compatibility

Dockhand reuses the **same `.dtu_hpc.json`** configuration format from DTU-HPC-CLI. No migration needed:

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
        "volumes": [...],
        "gpus": "all",
        "sync": true
    }
}
```

## Differences from DTU-HPC-CLI

| Feature | DTU-HPC-CLI | dockhand |
|---------|------------|----------|
| Command style | `dtu docker submit` | `dockhand submit` |
| HPC support | ✅ Full | ❌ Not included |
| Docker support | ✅ Yes (sub-group) | ✅ Yes (all 11 commands) |
| SSH/rsync | ✅ Yes | ✅ Yes |
| Dependencies | ~8 packages | ~4 packages (smaller) |
| Size | ~50KB | ~20KB |

## Development

To make changes to dockhand:

1. Clone/fork this repo
2. Modify files in `dockhand/`
3. Test with `python3 -m dockhand <command>` (after installing deps)
4. Commit changes
5. Optionally: open a PR if contributing improvements back to DTU-HPC-CLI

## Maintenance

Dockhand can now be maintained independently:
- Bug fixes don't need to wait for HPC team approval
- Docker-specific features can be added freely
- Version bumps are independent from DTU-HPC-CLI
- Can be published to PyPI separately if desired

## Future enhancements

Potential improvements specific to dockhand:
- Docker Compose support
- Kubernetes/Docker Swarm integration
- Local-only mode (drop SSH for purely local docker)
- Config auto-generation wizard
- Integration with container registries (Docker Hub, ECR, GCR)

## Reverting to DTU-HPC-CLI

If you need full HPC support, use the original [DTU-HPC-CLI](https://github.com/ChrisFugl/DTU-HPC-CLI):
```bash
pip install dtu-hpc-cli
```

dockhand is a **superset** for Docker workloads but does not include HPC job submission.
