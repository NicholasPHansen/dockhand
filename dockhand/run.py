"""Docker container execution and resubmission."""
import dataclasses
from typing import List

import typer
from git import InvalidGitRepositoryError, Repo
from rich.progress import Progress, SpinnerColumn, TextColumn

from dockhand.build import execute_build
from dockhand.client import get_client
from dockhand.config import DockerConfig, DockerResubmitConfig, cli_config
from dockhand.error import error_and_exit
from dockhand.history import add_to_history


def _build_docker_run_cmd(
    config: DockerConfig,
    commands: List[str],
    imagename: str,
    gpus: str | None,
    effective_ports: list[str] | None,
) -> str:
    """Build the docker run command string."""
    volumes = []
    if config.volumes is not None:
        volumes = [f"-v {v['hostpath']}:{v['containerpath']}:{v['permissions']}" for v in config.volumes]

    gpu_flags = [f"--gpus {gpus}"] if gpus is not None else []
    port_flags = [f"-p {mapping}" for mapping in effective_ports] if effective_ports is not None else []

    return " ".join(
        [
            "docker",
            "run",
            "--rm",
            *volumes,
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


def execute_queued_run(
    config: DockerConfig,
    commands: List[str],
    imagename: str | None = None,
    gpus: str | None = None,
    ports: list[str] | None = None,
    urgent: bool = False,
) -> int:
    """Submit a container run to the task spooler queue. Returns the local job ID."""
    from dockhand.queue import ts_make_urgent, ts_submit

    imagename = imagename or config.imagename
    gpus = gpus if gpus is not None else config.gpus
    effective_ports = ports if ports is not None else config.ports

    docker_cmd = _build_docker_run_cmd(config, commands, imagename, gpus, effective_ports)

    with get_client() as client:
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task(description="Queuing job", total=None)
            ts_job_id = ts_submit(client, docker_cmd, cwd=cli_config.remote_path)
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


def execute_submit(
    config: DockerConfig,
    commands: List[str],
    sync: bool,
    dockerfile: str | None = None,
    imagename: str | None = None,
    gpus: str | None = None,
    ports: list[str] | None = None,
    urgent: bool = False,
    verbose: bool = False,
):
    """Build the image and run a container (or queue it) with the given command(s)."""
    dockerfile = dockerfile or config.dockerfile
    imagename = imagename or config.imagename
    gpus = gpus if gpus is not None else config.gpus

    execute_build(config, sync, dockerfile=dockerfile, imagename=imagename, verbose=verbose)
    execute_queued_run(config, commands, imagename=imagename, gpus=gpus, ports=ports, urgent=urgent)


def execute_resubmit(docker_config: DockerConfig, resubmit_config: DockerResubmitConfig):
    """Resubmit a previous docker run with optional overrides."""
    from dockhand.history import get_history_entry, load_history

    history = load_history()

    if not history:
        error_and_exit("No docker history found. Submit a docker job first.")

    local_id = int(resubmit_config.container_id) if resubmit_config.container_id else None
    if local_id is not None:
        entry = get_history_entry(local_id)
        if entry is None:
            error_and_exit(f"Job #{local_id} not found in history.")
    else:
        entry = history[-1]

    original_config = entry["config"]

    # Prepare overrides (use provided values or fall back to original)
    commands = resubmit_config.commands if resubmit_config.commands is not None else original_config.get("commands", [])
    dockerfile = (
        resubmit_config.dockerfile if resubmit_config.dockerfile is not None else original_config.get("dockerfile")
    )
    imagename = resubmit_config.imagename if resubmit_config.imagename is not None else original_config.get("imagename")
    gpus = resubmit_config.gpus if resubmit_config.gpus is not None else original_config.get("gpus")

    updated_config = dataclasses.replace(docker_config, dockerfile=dockerfile, imagename=imagename, gpus=gpus)

    execute_submit(
        updated_config,
        commands,
        sync=False,
        dockerfile=dockerfile,
        imagename=imagename,
        gpus=gpus,
    )
