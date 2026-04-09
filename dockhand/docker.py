import dataclasses
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import List

import typer
from git import Repo
from rich.console import Console
from rich.progress import Progress
from rich.progress import SpinnerColumn
from rich.progress import TextColumn
from rich.table import Table

from dockhand.client import get_client
from dockhand.config import DockerConfig
from dockhand.config import DockerResubmitConfig
from dockhand.config import cli_config
from dockhand.error import error_and_exit
from dockhand.sync import execute_sync

DOCKER_HISTORY_FILE = Path(".dtu_docker_history.json")


def load_history() -> list[dict]:
    path = DOCKER_HISTORY_FILE
    if not path.exists():
        return []
    return json.loads(path.read_text())


def save_history(history: list[dict]):
    path = DOCKER_HISTORY_FILE
    path.write_text(json.dumps(history))


def add_to_history(config: DockerConfig, container_id: str, commands: List[str], branch: str | None = None):
    history = load_history()
    _d = {
        "dockerfile": config.dockerfile,
        "gpus": config.gpus,
        "volumes": config.volumes,
        "imagename": config.imagename,
        "commands": commands,
    }
    if branch is not None:
        _d["branch"] = branch
    history.append({"config": _d, "container_id": container_id, "timestamp": time.time()})
    save_history(history)


def execute_docker_history(config: DockerConfig):
    """Show history of past Docker runs."""
    if not DOCKER_HISTORY_FILE.exists():
        typer.echo(f"No history found in '{DOCKER_HISTORY_FILE}'. You might not have submitted any jobs yet.")
        return

    history = load_history()

    table = Table(title="Docker Run Commands", show_lines=True)
    table.add_column("Timestamp")
    table.add_column("Container ID(s)")
    table.add_column("Branch")
    table.add_column("Dockerfile")
    table.add_column("GPU(s)")
    table.add_column("Volume(s)")
    table.add_column("Imagename")
    table.add_column("Commands")

    for entry in history:
        timestamp = datetime.fromtimestamp(entry["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
        container_id = entry["container_id"]
        _config = entry["config"]
        branch = _config.get("branch") or "-"
        dockerfile = _config["dockerfile"]
        gpus = _config["gpus"] if _config["gpus"] else "-"
        volumes = "\n".join([f"{v['hostpath']}:{v['containerpath']}:{v['permissions']}" for v in _config["volumes"]])
        imagename = _config["imagename"]
        # support both old "arguments" key and new "commands" key
        cmds = _config.get("commands") or _config.get("arguments") or []
        commands_str = " ".join(cmds)
        table.add_row(str(timestamp), container_id, branch, dockerfile, gpus, volumes, imagename, commands_str)

    console = Console()
    console.print(table)


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


def execute_docker_volumes(config: DockerConfig):
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


def execute_docker_download(config: DockerConfig, path: str, local_path: str | None = None):
    """Download a file from a docker volume by its workdir-relative path."""
    result = _resolve_to_host(path, config)
    if result is None:
        error_and_exit(f"Path '{path}' does not match any configured docker volume.")

    host_path, _ = result
    ssh = cli_config.ssh

    # If no local_path provided, compute it from the workdir-relative path
    if local_path is None:
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


def execute_docker_stats(config: DockerConfig):
    """List running containers (docker ps)."""
    with get_client() as client:
        client.run("docker ps", cwd=cli_config.remote_path)


def execute_docker_logs(
    config: DockerConfig, *, container_id: str | None, imagename: str | None, all: bool, n: int | None
):
    """Show logs from a container."""
    imagename = imagename or config.imagename
    cmd = ["journalctl", f"IMAGE_NAME={imagename}", "-o cat", "--all"]

    if container_id is not None:
        if len(container_id) != 12:
            error_and_exit(f"Expected 12-character container ID, got: {container_id}")
        cmd.append(f"CONTAINER_ID={container_id}")
    elif not all:
        history = load_history()
        if not history:
            error_and_exit("No container history found. Provide --container-id or use --all.")
        cmd.append(f"CONTAINER_ID={history[-1]['container_id']}")

    if n is not None:
        cmd.append(f"-n {n}")

    with get_client() as client:
        client.run(" ".join(cmd), cwd=cli_config.remote_path)


def execute_docker_stop(config: DockerConfig, *, container_id: str | None):
    """Stop a running container."""
    if container_id is None:
        history = load_history()
        if not history:
            error_and_exit("No container history found. Provide --container-id.")
        container_id = history[-1]["container_id"]

    if len(container_id) != 12:
        error_and_exit(f"Expected 12-character container ID, got: {container_id}")

    cmd = f"docker container stop {container_id}"
    with get_client() as client:
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task(description="Stopping container", total=None)
            returncode, _ = client.run(cmd, cwd=cli_config.remote_path)
            progress.update(task, completed=True)

    if returncode != 0:
        error_and_exit(f"Stop command failed with return code {returncode}.")


def execute_docker_build(config: DockerConfig, sync: bool, dockerfile: str | None = None, imagename: str | None = None):
    """Build the Docker image."""
    if sync:
        execute_sync(confirm_changes=True)

    dockerfile = dockerfile or config.dockerfile
    imagename = imagename or config.imagename
    cmd = f"docker build -f {dockerfile} -t {imagename} ."
    with get_client() as client:
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task(description="Building image", total=None)
            returncode, _ = client.run(cmd, cwd=cli_config.remote_path)
            progress.update(task, completed=True)

    if returncode != 0:
        error_and_exit(f"Build command failed with return code {returncode}.")


def execute_docker_run(
    config: DockerConfig,
    commands: List[str],
    imagename: str | None = None,
    gpus: str | None = None,
):
    """Run a container from an already-built image."""
    imagename = imagename or config.imagename
    gpus = gpus if gpus is not None else config.gpus

    volumes = []
    if config.volumes is not None:
        volumes = [f"-v {v['hostpath']}:{v['containerpath']}:{v['permissions']}" for v in config.volumes]

    gpu_flags = []
    if gpus is not None:
        gpu_flags = [f"--gpus {gpus}"]

    ports = []
    if config.ports is not None:
        ports = [f"-p {mapping}" for mapping in config.ports]

    cmd = " ".join(
        [
            "docker",
            "run",
            "--log-driver=journald",
            "--rm",
            "-d",
            *volumes,
            *gpu_flags,
            *ports,
            imagename,
            *commands,
        ]
    )

    with get_client() as client:
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task(description="Starting container", total=None)
            returncode, stdout = client.run(cmd, cwd=cli_config.remote_path)
            progress.update(task, completed=True)

    if returncode != 0:
        error_and_exit(f"Run command failed with return code {returncode}.")

    container_id = stdout[:12]
    with Repo(cli_config.project_root) as repo:
        branch = repo.active_branch.name
    add_to_history(config, container_id, commands, branch)


def execute_docker_submit(
    config: DockerConfig,
    commands: List[str],
    sync: bool,
    dockerfile: str | None = None,
    imagename: str | None = None,
    gpus: str | None = None,
):
    """Build the image and run a container with the given command(s)."""
    dockerfile = dockerfile or config.dockerfile
    imagename = imagename or config.imagename
    gpus = gpus if gpus is not None else config.gpus

    execute_docker_build(config, sync, dockerfile=dockerfile, imagename=imagename)
    execute_docker_run(config, commands, imagename=imagename, gpus=gpus)


def execute_docker_resubmit(docker_config: DockerConfig, resubmit_config: DockerResubmitConfig):
    """Resubmit a previous docker run with optional overrides."""
    history = load_history()

    if not history:
        error_and_exit("No docker history found. Submit a docker job first.")

    # Use latest if no container_id provided
    container_id = resubmit_config.container_id or history[-1]["container_id"]

    # Find entry by container_id
    entry = None
    for hist_entry in history:
        if hist_entry["container_id"] == container_id:
            entry = hist_entry
            break

    if entry is None:
        error_and_exit(f"Container ID '{container_id}' not found in history.")

    original_config = entry["config"]

    # Prepare overrides (use provided values or fall back to original)
    commands = resubmit_config.commands if resubmit_config.commands is not None else original_config.get("commands", [])
    dockerfile = (
        resubmit_config.dockerfile if resubmit_config.dockerfile is not None else original_config.get("dockerfile")
    )
    imagename = resubmit_config.imagename if resubmit_config.imagename is not None else original_config.get("imagename")
    gpus = resubmit_config.gpus if resubmit_config.gpus is not None else original_config.get("gpus")

    # Create updated config by merging with original
    updated_config = dataclasses.replace(docker_config, dockerfile=dockerfile, imagename=imagename, gpus=gpus)

    execute_docker_submit(
        updated_config,
        commands,
        sync=False,
        dockerfile=dockerfile,
        imagename=imagename,
        gpus=gpus,
    )


def execute_docker_remove(config: DockerConfig, container_ids: list[str] | None = None, from_history: bool = False):
    """Remove container(s) from docker and optionally from history."""
    if not container_ids:
        # Remove latest if no container_ids provided
        history = load_history()
        if not history:
            error_and_exit("No container history found. Provide container IDs or submit a docker job first.")
        container_ids = [history[-1]["container_id"]]

    # Remove containers from docker
    with get_client() as client:
        for container_id in container_ids:
            if len(container_id) != 12:
                error_and_exit(f"Expected 12-character container ID, got: {container_id}")
            cmd = f"docker rm {container_id}"
            returncode, _ = client.run(cmd, cwd=cli_config.remote_path)
            if returncode == 0:
                typer.echo(f"Removed container {container_id}")
            else:
                typer.echo(f"Failed to remove container {container_id}")

    # Optionally remove from history
    if from_history:
        history = load_history()
        container_ids_set = set(container_ids)
        history = [entry for entry in history if entry["container_id"] not in container_ids_set]
        save_history(history)
        typer.echo(f"Removed {len(container_ids)} container(s) from history")
