"""Docker container lifecycle management (logs, stop, remove, stats)."""
import typer
from rich.progress import Progress, SpinnerColumn, TextColumn

from dockhand.client import get_client
from dockhand.config import DockerConfig, cli_config
from dockhand.error import error_and_exit
from dockhand.history import load_history, save_history


def execute_stats(config: DockerConfig):
    """List running containers (docker ps)."""
    with get_client() as client:
        client.run("docker ps", cwd=cli_config.remote_path)


def execute_logs(
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


def execute_stop(config: DockerConfig, *, container_id: str | None):
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


def execute_remove(config: DockerConfig, container_ids: list[str] | None = None, from_history: bool = False):
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
