"""Docker volume inspection and path resolution."""
import subprocess

import typer

from dockhand.config import DockerConfig, cli_config


def _workdir_relative(containerpath: str, workdir: str) -> str:
    """Convert an absolute container path to a workdir-relative path."""
    workdir = workdir.rstrip("/")
    containerpath = containerpath.rstrip("/")
    if containerpath.startswith(workdir + "/"):
        return containerpath[len(workdir) + 1 :]
    if containerpath == workdir:
        return "."
    return containerpath


def _resolve_to_host(relative_path: str, config: DockerConfig) -> tuple[str, str] | None:
    """Map a workdir-relative path back to a host path and volume hostpath."""
    workdir = config.workdir.rstrip("/")
    for volume in config.volumes:
        containerpath = volume["containerpath"].rstrip("/")
        hostpath = volume["hostpath"].rstrip("/")
        # Build the workdir-relative prefix for this volume
        vol_relative = _workdir_relative(containerpath, workdir)
        if relative_path.startswith(vol_relative + "/") or relative_path == vol_relative:
            # Strip the volume's relative prefix, append to hostpath
            suffix = relative_path[len(vol_relative) :]
            return hostpath + suffix, hostpath
    return None


def _ssh_find(hostpath: str) -> tuple[int, str]:
    """Run find on remote via SSH subprocess without printing output."""
    ssh = cli_config.ssh
    result = subprocess.run(
        [
            "ssh",
            "-i",
            ssh.identityfile,
            f"{ssh.user}@{ssh.hostname}",
            f"find {hostpath} -type f",
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout


def execute_volumes(config: DockerConfig):
    """List files in docker-mounted volumes using workdir-relative paths."""
    if not config.volumes:
        typer.echo("No volumes configured.")
        return

    for volume in config.volumes:
        hostpath = volume["hostpath"].rstrip("/")
        containerpath = volume["containerpath"]
        vol_relative = _workdir_relative(containerpath, config.workdir)
        typer.echo(f"\n{vol_relative}/:")
        exit_code, stdout = _ssh_find(hostpath)
        if exit_code != 0 or not stdout.strip():
            typer.echo("  (empty or inaccessible)")
            continue
        for line in stdout.strip().splitlines():
            suffix = line[len(hostpath) :]
            typer.echo(f"  {vol_relative}{suffix}")
