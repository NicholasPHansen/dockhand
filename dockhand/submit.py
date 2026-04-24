"""Docker container submission and queuing."""
from typing import List

import typer
from git import InvalidGitRepositoryError, Repo
from rich.progress import Progress, SpinnerColumn, TextColumn

from dockhand.client import get_client
from dockhand.config import DockerConfig, cli_config
from dockhand.history import add_to_history
from dockhand.sync import execute_sync


def _build_docker_run_cmd(
    config: DockerConfig,
    commands: List[str],
    imagename: str,
    gpus: str | None,
    effective_ports: list[str] | None,
) -> str:
    """Build the docker run command string."""
    if config.containerworkdir == "/":
        typer.echo(
            "Warning: containerworkdir is '/' — mounting code at the container root will shadow the entire filesystem.",
            err=True,
        )

    # Implicit code mount: remote project path → containerworkdir
    code_mount = f"-v {cli_config.remote_path}:{config.containerworkdir}:rw"

    data_volumes = []
    if config.volumes is not None:
        data_volumes = [f"-v {v['hostpath']}:{v['containerpath']}:{v['permissions']}" for v in config.volumes]

    gpu_flags = [f"--gpus {gpus}"] if gpus is not None else []
    port_flags = [f"-p {mapping}" for mapping in effective_ports] if effective_ports is not None else []

    return " ".join(
        [
            "docker",
            "run",
            "--rm",
            code_mount,
            *data_volumes,
            *gpu_flags,
            *port_flags,
            imagename,
            *commands,
        ]
    )


def _get_branch() -> str | None:
    try:
        with Repo(cli_config.project_root) as repo:
            return repo.active_branch.name
    except (InvalidGitRepositoryError, Exception):
        return None


def execute_submit(
    config: DockerConfig,
    commands: List[str],
    sync: bool,
    imagename: str | None = None,
    gpus: str | None = None,
    ports: list[str] | None = None,
    urgent: bool = False,
    slots: int | None = None,
) -> int:
    """Optionally sync code, then queue a container run. Returns the local job ID."""
    from dockhand.queue import ts_make_urgent, ts_submit

    if sync:
        execute_sync(confirm_changes=True)

    imagename = imagename or config.imagename
    gpus = gpus if gpus is not None else config.gpus
    effective_ports = ports if ports is not None else config.ports
    effective_slots = slots if slots is not None else config.slots

    docker_cmd = _build_docker_run_cmd(config, commands, imagename, gpus, effective_ports)

    with get_client() as client:
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task(description="Queuing job", total=None)
            ts_job_id = ts_submit(client, docker_cmd, cwd=cli_config.remote_path, slots=effective_slots)
            if urgent:
                ts_make_urgent(client, ts_job_id, cwd=cli_config.remote_path)
            progress.update(task, completed=True)

    host = cli_config.ssh.hostname if cli_config.ssh else "localhost"
    local_id = add_to_history(
        config,
        commands=commands,
        ts_job_id=ts_job_id,
        branch=_get_branch(),
        ports=effective_ports,
        host=host,
    )

    label = "urgent job" if urgent else "job"
    typer.echo(f"Queued {label} #{local_id}")
    return local_id
