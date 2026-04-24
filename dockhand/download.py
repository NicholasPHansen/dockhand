"""Download files from docker volumes."""
import subprocess
from pathlib import Path

from rich.progress import Progress, SpinnerColumn, TextColumn

from dockhand.config import DockerConfig, cli_config
from dockhand.error import error_and_exit
from dockhand.volumes import _resolve_to_host


def execute_download(config: DockerConfig, path: str, local_path: str | None = None):
    """Download a file from a docker volume by its workdir-relative path."""
    result = _resolve_to_host(path, config)
    if result is None:
        error_and_exit(f"Path '{path}' does not match any configured docker volume.")

    host_path, _ = result
    ssh = cli_config.ssh

    # If no local_path provided, mirror the remote path structure locally.
    # For directory downloads (trailing slash), use the directory itself as the destination
    # so rsync places contents at reports/figures/ rather than reports/.
    # For file downloads, use the parent directory so rsync places the file correctly.
    if local_path is None:
        if path.endswith("/"):
            dest = cli_config.project_root / Path(path.rstrip("/"))
            dest.mkdir(parents=True, exist_ok=True)
            local_path = str(dest)
        else:
            parent_dir = cli_config.project_root / Path(path).parent
            parent_dir.mkdir(parents=True, exist_ok=True)
            local_path = str(parent_dir)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
    ) as progress:
        task = progress.add_task(description="Downloading", total=None)
        progress.start()
        try:
            command = [
                "rsync",
                "-avz",
                "-e",
                f"ssh -i {ssh.identityfile}",
                f"{ssh.user}@{ssh.hostname}:{host_path}",
                local_path,
            ]
            subprocess.run(command, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            error_and_exit(f"Download failed:\n{e.stderr.decode()}")
        progress.update(task, completed=True)
