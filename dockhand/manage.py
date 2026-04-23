"""Docker container lifecycle management (logs, stop, remove, stats)."""
import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from dockhand.client import get_client
from dockhand.config import DockerConfig, cli_config
from dockhand.error import error_and_exit
from dockhand.history import load_history, save_history


def execute_stats(config: DockerConfig):
    """List jobs: queue contents when queue is enabled, otherwise docker ps."""
    if cli_config.queue.enabled:
        from dockhand.queue import ts_list

        with get_client() as client:
            jobs = ts_list(client, cwd=cli_config.remote_path)

        if not jobs:
            typer.echo("No jobs in queue.")
            return

        table = Table(title="Job Queue")
        table.add_column("Job ID")
        table.add_column("Status")
        table.add_column("Command")
        for job in jobs:
            table.add_row(str(job["id"]), job["state"], job["command"])

        Console().print(table)
    else:
        with get_client() as client:
            client.run("docker ps", cwd=cli_config.remote_path)


def execute_logs(
    config: DockerConfig,
    *,
    job_id: int | None,
    container_id: str | None,
    imagename: str | None,
    all: bool,
    n: int | None,
):
    """Show logs from a container."""
    imagename = imagename or config.imagename

    if cli_config.queue.enabled:
        # Resolve job ID → container ID via ts output
        from dockhand.queue import ts_get_container_id

        if job_id is None:
            history = load_history()
            queued = [e for e in history if e.get("ts_job_id") is not None]
            if not queued:
                error_and_exit("No queued job history found. Provide a job ID.")
            job_id = queued[-1]["ts_job_id"]

        with get_client() as client:
            container_id = ts_get_container_id(client, job_id, cwd=cli_config.remote_path)

        if not container_id:
            error_and_exit(
                f"Could not get container ID for job {job_id}. "
                "The job may still be queued and not yet started."
            )
    else:
        if container_id is not None and len(container_id) != 12:
            error_and_exit(f"Expected 12-character container ID, got: {container_id}")

    cmd = ["journalctl", f"IMAGE_NAME={imagename}", "-o cat", "--all"]

    if container_id is not None:
        cmd.append(f"CONTAINER_ID={container_id}")
    elif not all:
        history = load_history()
        if not history:
            error_and_exit("No container history found. Provide --container-id or use --all.")
        last_container_id = history[-1].get("container_id")
        if not last_container_id:
            error_and_exit("Last history entry has no container ID. Provide an explicit ID.")
        cmd.append(f"CONTAINER_ID={last_container_id}")

    if n is not None:
        cmd.append(f"-n {n}")

    with get_client() as client:
        client.run(" ".join(cmd), cwd=cli_config.remote_path)


def execute_stop(config: DockerConfig, *, job_id: int | None = None, container_id: str | None = None):
    """Stop a running container or cancel a queued job."""
    if cli_config.queue.enabled:
        from dockhand.queue import ts_get_container_id, ts_get_job, ts_kill, ts_remove

        if job_id is None:
            history = load_history()
            queued = [e for e in history if e.get("ts_job_id") is not None]
            if not queued:
                error_and_exit("No queued job history found. Provide a job ID.")
            job_id = queued[-1]["ts_job_id"]

        with get_client() as client:
            job = ts_get_job(client, job_id, cwd=cli_config.remote_path)

            if job is None:
                error_and_exit(f"Job {job_id} not found in task spooler.")

            if job["state"] == "queued":
                if ts_remove(client, job_id, cwd=cli_config.remote_path):
                    typer.echo(f"Removed queued job {job_id}.")
                else:
                    error_and_exit(f"Failed to remove job {job_id}.")

            elif job["state"] == "running":
                resolved_id = ts_get_container_id(client, job_id, cwd=cli_config.remote_path)
                if resolved_id:
                    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
                        task = progress.add_task(description="Stopping container", total=None)
                        returncode, _ = client.run(
                            f"docker container stop {resolved_id}", cwd=cli_config.remote_path
                        )
                        progress.update(task, completed=True)
                    if returncode != 0:
                        error_and_exit("Stop command failed.")
                    typer.echo(f"Stopped job {job_id} (container {resolved_id}).")
                else:
                    # Fall back to ts kill
                    if ts_kill(client, job_id, cwd=cli_config.remote_path):
                        typer.echo(f"Killed job {job_id}.")
                    else:
                        error_and_exit(f"Failed to kill job {job_id}.")
            else:
                typer.echo(f"Job {job_id} is already {job['state']}.")
    else:
        if container_id is None:
            history = load_history()
            if not history:
                error_and_exit("No container history found. Provide a container ID.")
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


def execute_remove(
    config: DockerConfig,
    job_ids: list[int] | None = None,
    container_ids: list[str] | None = None,
    from_history: bool = False,
):
    """Remove job(s) from queue (queue mode) or docker container(s) (direct mode)."""
    if cli_config.queue.enabled:
        from dockhand.queue import ts_get_job, ts_remove

        if not job_ids:
            history = load_history()
            queued = [e for e in history if e.get("ts_job_id") is not None]
            if not queued:
                error_and_exit("No queued job history found. Provide a job ID.")
            job_ids = [queued[-1]["ts_job_id"]]

        with get_client() as client:
            for job_id in job_ids:
                job = ts_get_job(client, job_id, cwd=cli_config.remote_path)
                if job and job["state"] == "running":
                    error_and_exit(f"Job {job_id} is currently running. Use 'stop' to terminate it.")
                if ts_remove(client, job_id, cwd=cli_config.remote_path):
                    typer.echo(f"Removed job {job_id} from queue.")
                else:
                    typer.echo(f"Failed to remove job {job_id} (it may have already finished).")

        if from_history:
            history = load_history()
            ids_set = set(job_ids)
            history = [e for e in history if e.get("ts_job_id") not in ids_set]
            save_history(history)
            typer.echo(f"Removed {len(job_ids)} job(s) from history.")
    else:
        if not container_ids:
            history = load_history()
            if not history:
                error_and_exit("No container history found. Provide container IDs or submit a docker job first.")
            container_ids = [history[-1]["container_id"]]

        with get_client() as client:
            for container_id in container_ids:
                if len(container_id) != 12:
                    error_and_exit(f"Expected 12-character container ID, got: {container_id}")
                returncode, _ = client.run(f"docker rm {container_id}", cwd=cli_config.remote_path)
                if returncode == 0:
                    typer.echo(f"Removed container {container_id}.")
                else:
                    typer.echo(f"Failed to remove container {container_id}.")

        if from_history:
            history = load_history()
            ids_set = set(container_ids)
            history = [e for e in history if e.get("container_id") not in ids_set]
            save_history(history)
            typer.echo(f"Removed {len(container_ids)} container(s) from history.")
