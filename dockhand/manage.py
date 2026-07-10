"""Docker container lifecycle management (logs, stop, remove, stats)."""

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from dockhand.client import get_client, get_client_for_host
from dockhand.config import DockerConfig, cli_config
from dockhand.error import error_and_exit
from dockhand.history import get_history_entry, load_history, save_history
from dockhand.transport import entry_handle, get_transport, transport_for_entry

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


def execute_stats(config: DockerConfig, all: bool = False):
    """List live jobs for the active transport (queue or direct docker)."""
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
        str(entry_handle(e)): e["local_id"]
        for e in history
        if entry_handle(e) is not None and "local_id" in e
    }

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("ID", justify="right", style="bold")
    table.add_column("Status")
    table.add_column("Command")

    for job in jobs:
        state = job["state"]
        style = _STATE_STYLES.get(state, "")
        status_text = Text(state, style=style)
        local_id = handle_to_local.get(str(job["handle"]))
        id_str = str(local_id) if local_id is not None else f"{transport.name}:{job['handle']}"
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
    """Show logs from a job (via the tsp output file, or ``docker logs``)."""
    local_id, entry = _resolve_entry(job_id)
    host = entry.get("host", "localhost")
    with get_client_for_host(host) as client:
        returncode = transport_for_entry(entry).logs(client, entry, n=n, follow=follow)
    if returncode != 0:
        error_and_exit(f"Could not read logs for job #{local_id}. The job may still be queued and not yet started.")


def execute_stop(config: DockerConfig, *, job_id: int | None = None):
    """Stop a running job or cancel a queued one."""
    local_id, entry = _resolve_entry(job_id)
    host = entry.get("host", "localhost")
    with get_client_for_host(host) as client:
        if transport_for_entry(entry).stop(client, entry):
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
