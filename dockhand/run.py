"""Docker container execution and resubmission."""
import dataclasses
from typing import List

from git import Repo
from rich.progress import Progress, SpinnerColumn, TextColumn

from dockhand.build import execute_build
from dockhand.client import get_client
from dockhand.config import DockerConfig, DockerResubmitConfig, cli_config
from dockhand.error import error_and_exit
from dockhand.history import add_to_history


def execute_run(
    config: DockerConfig,
    commands: List[str],
    imagename: str | None = None,
    gpus: str | None = None,
    ports: list[str] | None = None,
):
    """Run a container from an already-built image."""
    imagename = imagename or config.imagename
    gpus = gpus if gpus is not None else config.gpus
    effective_ports = ports if ports is not None else config.ports

    volumes = []
    if config.volumes is not None:
        volumes = [f"-v {v['hostpath']}:{v['containerpath']}:{v['permissions']}" for v in config.volumes]

    gpu_flags = []
    if gpus is not None:
        gpu_flags = [f"--gpus {gpus}"]

    port_flags = []
    if effective_ports is not None:
        port_flags = [f"-p {mapping}" for mapping in effective_ports]

    cmd = " ".join(
        [
            "docker",
            "run",
            "--log-driver=journald",
            "--rm",
            "-d",
            *volumes,
            *gpu_flags,
            *port_flags,
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
    host = cli_config.ssh.hostname if cli_config.ssh else "localhost"
    add_to_history(config, container_id, commands, branch, ports=effective_ports, host=host)


def execute_submit(
    config: DockerConfig,
    commands: List[str],
    sync: bool,
    dockerfile: str | None = None,
    imagename: str | None = None,
    gpus: str | None = None,
    ports: list[str] | None = None,
):
    """Build the image and run a container with the given command(s)."""
    dockerfile = dockerfile or config.dockerfile
    imagename = imagename or config.imagename
    gpus = gpus if gpus is not None else config.gpus

    execute_build(config, sync, dockerfile=dockerfile, imagename=imagename)
    execute_run(config, commands, imagename=imagename, gpus=gpus, ports=ports)


def execute_resubmit(docker_config: DockerConfig, resubmit_config: DockerResubmitConfig):
    """Resubmit a previous docker run with optional overrides."""
    from dockhand.history import load_history

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

    execute_submit(
        updated_config,
        commands,
        sync=False,
        dockerfile=dockerfile,
        imagename=imagename,
        gpus=gpus,
    )
