"""Docker container lifecycle management (logs, stop, remove, stats)."""
import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from dockhand.client import get_client
from dockhand.config import DockerConfig, cli_config
from dockhand.error import error_and_exit
from dockhand.history import load_history, save_history
from dockhand.queue import (
    ts_get_job,
    ts_kill,
    ts_list,
    ts_remove,
)

_STATE_STYLES = {
    "running": "bold green",
    "queued": "yellow",
    "finished": "dim",
    "failed": "bold red",
    "skipped": "dim",
}


def _user_command(full_cmd: str, imagename: str) -> str:
    """Strip docker run boilerplate, returning only the user command."""
    if imagename in full_cmd:
        return full_cmd.split(imagename, 1)[-1].strip()
    return full_cmd


def execute_stats(config: DockerConfig):
    """List all jobs in the task spooler queue."""
    with get_client() as client:
        jobs = ts_list(client, cwd=cli_config.remote_path)

    if not jobs:
        typer.echo("No jobs in queue.")
        return

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("ID", justify="right", style="bold")
    table.add_column("Status")
    table.add_column("Command")

    for job in jobs:
        state = job["state"]
        style = _STATE_STYLES.get(state, "")
        status_text = Text(state, style=style)
        user_cmd = _user_command(job["command"], config.imagename)
        table.add_row(str(job["id"]), status_text, user_cmd)

    Console().print(table)


def execute_logs(
    config: DockerConfig,
    *,
    job_id: int | None,
    n: int | None,
):
    """Show logs from a job via tsp output file."""
    if job_id is None:
        history = load_history()
        queued = [e for e in history if e.get("ts_job_id") is not None]
        if not queued:
            error_and_exit("No job history found. Provide a job ID.")
        job_id = queued[-1]["ts_job_id"]

    if n is not None:
        cmd = f"tail -n {n} $(tsp -o {job_id})"
    else:
        cmd = f"cat $(tsp -o {job_id})"

    with get_client() as client:
        returncode, _ = client.run(cmd, cwd=cli_config.remote_path)
    if returncode != 0:
        error_and_exit(
            f"Could not read logs for job {job_id}. "
            "The job may still be queued and not yet started."
        )


def execute_stop(config: DockerConfig, *, job_id: int | None = None, container_id: str | None = None):
    """Stop a running job or cancel a queued one."""
    if job_id is None:
        history = load_history()
        queued = [e for e in history if e.get("ts_job_id") is not None]
        if not queued:
            error_and_exit("No job history found. Provide a job ID.")
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
            if ts_kill(client, job_id, cwd=cli_config.remote_path):
                typer.echo(f"Stopped job {job_id}.")
            else:
                error_and_exit(f"Failed to stop job {job_id}.")
        else:
            typer.echo(f"Job {job_id} is already {job['state']}.")


def execute_remove(
    config: DockerConfig,
    job_ids: list[int] | None = None,
    container_ids: list[str] | None = None,
    from_history: bool = False,
):
    """Remove pending job(s) from the queue."""
    if not job_ids:
        history = load_history()
        queued = [e for e in history if e.get("ts_job_id") is not None]
        if not queued:
            error_and_exit("No job history found. Provide a job ID.")
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
