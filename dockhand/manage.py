"""Docker container lifecycle management (logs, stop, remove, stats)."""
import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from dockhand.client import get_client
from dockhand.config import DockerConfig, cli_config
from dockhand.error import error_and_exit
from dockhand.history import get_history_entry, load_history, save_history
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

    history = load_history()
    ts_to_local = {e["ts_job_id"]: e["local_id"] for e in history if "ts_job_id" in e and "local_id" in e}

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("ID", justify="right", style="bold")
    table.add_column("Status")
    table.add_column("Command")

    for job in jobs:
        state = job["state"]
        style = _STATE_STYLES.get(state, "")
        status_text = Text(state, style=style)
        local_id = ts_to_local.get(job["id"])
        id_str = str(local_id) if local_id is not None else f"ts:{job['id']}"
        user_cmd = _user_command(job["command"], config.imagename)
        table.add_row(id_str, status_text, user_cmd)

    Console().print(table)


def _resolve_entry(job_id: int | None) -> tuple[int, dict]:
    """Resolve a local job ID (or default to last) to (local_id, history_entry)."""
    history = load_history()
    if not history:
        error_and_exit("No job history found. Provide a job ID.")
    if job_id is None:
        entry = history[-1]
        return entry["local_id"], entry
    entry = get_history_entry(job_id)
    if entry is None:
        error_and_exit(f"Job #{job_id} not found in history.")
    return job_id, entry


def execute_logs(
    config: DockerConfig,
    *,
    job_id: int | None,
    n: int | None,
    follow: bool,
):
    """Show logs from a job via the tsp output file."""
    local_id, entry = _resolve_entry(job_id)
    ts_job_id = entry["ts_job_id"]

    if follow:
        cmd = f"tail -f $(tsp -o {ts_job_id})"
    elif n is not None:
        cmd = f"tail -n {n} $(tsp -o {ts_job_id})"
    else:
        cmd = f"cat $(tsp -o {ts_job_id})"

    with get_client() as client:
        returncode, _ = client.run(cmd, cwd=cli_config.remote_path)
    if returncode != 0:
        error_and_exit(
            f"Could not read logs for job #{local_id}. "
            "The job may still be queued and not yet started."
        )


def execute_stop(config: DockerConfig, *, job_id: int | None = None):
    """Stop a running job or cancel a queued one."""
    local_id, entry = _resolve_entry(job_id)
    ts_job_id = entry["ts_job_id"]

    with get_client() as client:
        job = ts_get_job(client, ts_job_id, cwd=cli_config.remote_path)

        if job is None:
            error_and_exit(f"Job #{local_id} (tsp {ts_job_id}) not found in task spooler.")

        if job["state"] != "running":
            error_and_exit(f"Job #{local_id} is not running (state: {job['state']}). Use 'remove' for queued jobs.")

        if ts_kill(client, ts_job_id, cwd=cli_config.remote_path):
            typer.echo(f"Stopped job #{local_id}.")
        else:
            error_and_exit(f"Failed to stop job #{local_id}.")


def execute_remove(
    config: DockerConfig,
    job_ids: list[int] | None = None,
    from_history: bool = False,
):
    """Remove pending job(s) from the queue."""
    if not job_ids:
        history = load_history()
        if not history:
            error_and_exit("No job history found. Provide a job ID.")
        job_ids = [history[-1]["local_id"]]

    removed = []
    with get_client() as client:
        for local_id in job_ids:
            entry = get_history_entry(local_id)
            if entry is None:
                typer.echo(f"Job #{local_id} not found in history.")
                continue
            ts_job_id = entry["ts_job_id"]
            job = ts_get_job(client, ts_job_id, cwd=cli_config.remote_path)
            if job and job["state"] != "queued":
                error_and_exit(
                    f"Job #{local_id} is not queued (state: {job['state']}). Use 'stop' to terminate running jobs."
                )
            if ts_remove(client, ts_job_id, cwd=cli_config.remote_path):
                typer.echo(f"Removed job #{local_id} from queue.")
                removed.append(local_id)
            else:
                typer.echo(f"Failed to remove job #{local_id} (it may have already finished).")

    if from_history and removed:
        history = load_history()
        ids_set = set(removed)
        history = [e for e in history if e.get("local_id") not in ids_set]
        save_history(history)
        typer.echo(f"Removed {len(removed)} job(s) from history.")
