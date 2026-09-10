"""Docker container lifecycle management (logs, stop, remove, stats)."""

import time
from datetime import datetime

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from dockhand.client import get_client, get_client_for_host
from dockhand.config import DockerConfig, cli_config
from dockhand.error import error_and_exit
from dockhand.history import get_history_entry, load_history, mark_job_time, mark_stopped, save_history
from dockhand.transport import entry_handle, get_transport, transport_for_entry

_STATE_STYLES = {
    "running": "bold green",
    "queued": "yellow",
    "finished": "dim",
    "stopped": "yellow",
    "failed": "bold red",
    "skipped": "dim",
}


def _user_command(full_cmd: str, imagename: str) -> str:
    """Strip docker run boilerplate, returning only the user command."""
    if imagename in full_cmd:
        return full_cmd.split(imagename, 1)[-1].strip()
    return full_cmd


_JOBS_DISPLAY_LIMIT = 30

_TERMINAL_STATES = ("finished", "failed", "stopped")


def _format_duration(seconds: float) -> str:
    """Compact elapsed-time string, e.g. ``45s``, ``5m30s``, ``2h15m``, ``1d04h``."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s" if seconds else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h{minutes:02d}m" if minutes else f"{hours}h"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours:02d}h" if hours else f"{days}d"


def _format_time(ts: float | None) -> str:
    if ts is None:
        return "-"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def execute_stats(config: DockerConfig, all: bool = False):
    """List live jobs for the active transport (queue or direct docker).

    Defaults to the most recent 30 jobs, newest (highest ID) first. ``--all``
    lifts the 30-job cap and also includes finished/failed/stopped jobs.

    Start/end times aren't available from the queue or docker directly, so they're
    recorded the first time a job is *observed* running or finished (i.e. the first
    time this command happens to be run while the job is in that state). This means
    a job never checked on while running will show no start time once it finishes.
    """
    transport = get_transport()
    with get_client() as client:
        jobs = transport.list_jobs(client)

    if not all:
        jobs = [j for j in jobs if j["state"] in ("running", "queued", "finished")]

    if not jobs:
        typer.echo("No active jobs." if not all else "No jobs.")
        return

    history = load_history()
    handle_to_local = {
        str(entry_handle(e)): e["local_id"] for e in history if entry_handle(e) is not None and "local_id" in e
    }
    entry_by_local = {e["local_id"]: e for e in history if "local_id" in e}
    stopped_locals = {e["local_id"] for e in history if e.get("stopped")}

    jobs.sort(key=lambda j: handle_to_local.get(str(j["handle"]), -1), reverse=True)
    if not all:
        jobs = jobs[:_JOBS_DISPLAY_LIMIT]

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("ID", justify="right", style="bold")
    table.add_column("Status")
    table.add_column("Started")
    table.add_column("Ended")
    table.add_column("Duration")
    table.add_column("Command")

    now = time.time()
    history_changed = False

    for job in jobs:
        state = job["state"]
        local_id = handle_to_local.get(str(job["handle"]))
        if local_id in stopped_locals and state in ("finished", "failed"):
            state = "stopped"

        entry = entry_by_local.get(local_id)
        if entry is not None:
            if state == "running" and "started_at" not in entry:
                entry["started_at"] = now
                history_changed = True
            elif state in _TERMINAL_STATES and "ended_at" not in entry:
                entry["ended_at"] = now
                history_changed = True

        started_at = entry.get("started_at") if entry else None
        ended_at = entry.get("ended_at") if entry else None
        duration_str = _format_duration((ended_at or now) - started_at) if started_at is not None else "-"

        style = _STATE_STYLES.get(state, "")
        status_text = Text(state, style=style)
        id_str = str(local_id) if local_id is not None else f"{transport.name}:{job['handle']}"
        user_cmd = _user_command(job["command"], config.imagename)
        table.add_row(id_str, status_text, _format_time(started_at), _format_time(ended_at), duration_str, user_cmd)

    if history_changed:
        save_history(history)

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


def _duration_header(local_id: int, state: str, started_at: float | None, ended_at: float | None, now: float) -> str:
    if state == "queued":
        return f"Job #{local_id} — queued (not started yet)."
    if state == "running":
        duration = _format_duration(now - started_at) if started_at is not None else "unknown"
        return f"Job #{local_id} — running for {duration}."
    if started_at is not None and ended_at is not None:
        return f"Job #{local_id} — {state} in {_format_duration(ended_at - started_at)}."
    return f"Job #{local_id} — {state}."


def execute_logs(
    config: DockerConfig,
    *,
    job_id: int | None,
    n: int | None,
    follow: bool,
):
    """Show logs from a job (via the tsp output file, or ``docker logs``)."""
    local_id, entry = _resolve_entry(job_id)
    host = entry.get("host", "localhost")
    transport = transport_for_entry(entry)
    with get_client_for_host(host) as client:
        jobs = transport.list_jobs(client)
        job = next((j for j in jobs if str(j["handle"]) == str(entry_handle(entry))), None)
        if job is not None:
            now = time.time()
            state = job["state"]
            if entry.get("stopped") and state in ("finished", "failed"):
                state = "stopped"
            if state == "running" and "started_at" not in entry:
                mark_job_time(local_id, started_at=now)
                entry["started_at"] = now
            elif state in _TERMINAL_STATES and "ended_at" not in entry:
                mark_job_time(local_id, ended_at=now)
                entry["ended_at"] = now
            typer.echo(_duration_header(local_id, state, entry.get("started_at"), entry.get("ended_at"), now))
        returncode = transport.logs(client, entry, n=n, follow=follow)
    if returncode != 0:
        error_and_exit(f"Could not read logs for job #{local_id}. The job may still be queued and not yet started.")


def execute_stop(config: DockerConfig, *, job_id: int | None = None):
    """Stop a running job or cancel a queued one."""
    local_id, entry = _resolve_entry(job_id)
    host = entry.get("host", "localhost")
    with get_client_for_host(host) as client:
        if transport_for_entry(entry).stop(client, entry):
            mark_stopped(local_id)
            typer.echo(f"Stopped job #{local_id}.")
        else:
            error_and_exit(f"Failed to stop job #{local_id}.")


def execute_remove(
    config: DockerConfig,
    job_ids: list[int] | None = None,
    from_history: bool = False,
):
    """Remove pending job(s) from the queue, or clean up direct-run containers."""
    if not job_ids:
        history = load_history()
        if not history:
            error_and_exit("No job history found. Provide a job ID.")
        job_ids = [history[-1]["local_id"]]

    removed = []
    for local_id in job_ids:
        entry = get_history_entry(local_id)
        if entry is None:
            typer.echo(f"Job #{local_id} not found in history.")
            continue
        host = entry.get("host", "localhost")
        with get_client_for_host(host) as client:
            if transport_for_entry(entry).remove(client, entry):
                typer.echo(f"Removed job #{local_id}.")
                removed.append(local_id)
            else:
                typer.echo(f"Failed to remove job #{local_id} (it may have already finished).")

    if from_history and removed:
        history = load_history()
        ids_set = set(removed)
        history = [e for e in history if e.get("local_id") not in ids_set]
        save_history(history)
        typer.echo(f"Removed {len(removed)} job(s) from history.")


def _baked_image_refs(history: list[dict]) -> dict[str, list]:
    """Map each distinct baked image tag in history to the job IDs that used it.

    Only images dockhand built for bake delivery qualify — their ``image_ref`` differs
    from the base ``imagename``. Mount jobs (``image_ref`` == base name, or absent) are
    never pruned since dockhand didn't create those tags.
    """
    refs: dict[str, list] = {}
    for entry in history:
        cfg = entry.get("config", {})
        ref = cfg.get("image_ref")
        if ref and ref != cfg.get("imagename"):
            refs.setdefault(ref, []).append(entry.get("local_id"))
    return refs


def execute_prune(config: DockerConfig, *, yes: bool = False, dry_run: bool = False):
    """Remove baked images that no active (running/queued) job still references."""
    history = load_history()
    baked = _baked_image_refs(history)
    if not baked:
        typer.echo("No baked images to prune.")
        return

    # Keep images referenced by jobs that are still running or queued.
    transport = get_transport()
    with get_client() as client:
        jobs = transport.list_jobs(client)
    active_handles = {str(j["handle"]) for j in jobs if j["state"] in ("running", "queued")}
    in_use = {
        entry["config"]["image_ref"]
        for entry in history
        if str(entry_handle(entry)) in active_handles and entry.get("config", {}).get("image_ref")
    }

    candidates = [ref for ref in baked if ref not in in_use]
    if not candidates:
        typer.echo("Nothing to prune — all baked images are in use by active jobs.")
        return

    typer.echo("The following baked images will be removed:")
    for ref in candidates:
        job_ids = ", ".join(str(i) for i in baked[ref] if i is not None)
        typer.echo(f"  - {ref} (jobs: {job_ids})")

    if dry_run:
        return
    if not yes and not typer.confirm("Remove these images?"):
        typer.echo("Aborted.")
        return

    removed = 0
    with get_client() as client:
        for ref in candidates:
            returncode, _ = client.run(f"docker image rm {ref}", cwd=cli_config.remote_path, capture=True)
            if returncode == 0:
                typer.echo(f"Removed {ref}")
                removed += 1
            else:
                typer.echo(f"Could not remove {ref} (in use or already gone).")
    typer.echo(f"Pruned {removed} image(s).")
