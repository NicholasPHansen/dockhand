"""Docker container run history management and tracking."""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import List

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from dockhand.config import DockerConfig, cli_config

DOCKER_HISTORY_FILE = Path(".dockhand_history.json")


def load_history() -> list[dict]:
    """Load container run history from disk."""
    # path = DOCKER_HISTORY_FILE
    path = cli_config.history_path
    if not path.exists():
        return []
    return json.loads(path.read_text())


def save_history(history: list[dict]):
    """Save container run history to disk."""
    # path = DOCKER_HISTORY_FILE
    path = cli_config.history_path
    path.write_text(json.dumps(history))


def _next_local_id(history: list[dict]) -> int:
    if not history:
        return 1
    return max((e.get("local_id", 0) for e in history), default=0) + 1


def reserve_local_id() -> int:
    """Peek the next local job ID without persisting it.

    Submitting needs the ID before the job runs (e.g. to name the container), so it
    is reserved here and passed to :func:`add_to_history` once the job has started.
    """
    return _next_local_id(load_history())


def add_to_history(
    config: DockerConfig,
    commands: List[str],
    *,
    local_id: int,
    handle: dict,
    image_ref: str | None = None,
    branch: str | None = None,
    ports: list[str] | None = None,
    host: str | None = None,
) -> int:
    """Add a started job to the history file. Returns the local job ID.

    ``handle`` carries the transport-specific job handle (e.g. ``transport`` name and
    a ``ts_job_id`` or container ``handle``) and is merged into the entry. ``image_ref``
    is the exact image that ran (a resolved baked tag, or the base image name for mount
    delivery) so the job can be reproduced verbatim on resubmit.
    """
    history = load_history()
    _d = {
        "gpus": config.gpus,
        "volumes": config.volumes,
        "imagename": config.imagename,
        "commands": commands,
        "ports": ports,
    }
    if image_ref is not None:
        _d["image_ref"] = image_ref
    if branch is not None:
        _d["branch"] = branch
    entry = {
        "local_id": local_id,
        "timestamp": time.time(),
        "config": _d,
        **handle,
    }
    if host is not None:
        entry["host"] = host
    history.append(entry)
    save_history(history)
    return local_id


def job_id(entry: dict) -> int | None:
    """The job ID shown to users and taken by `logs`/`stop`/`urgent`/`remove`/`resubmit`.

    Queued jobs use task spooler's own job ID: ts runs one queue per host, so it is unique across
    every project sharing it, where per-project local IDs repeat. Direct ``docker run`` jobs have
    no such ID and keep the local one.
    """
    return entry.get("ts_job_id", entry.get("local_id"))


def get_history_entry(id: int) -> dict | None:
    """Look up a history entry by job ID (see ``job_id``).

    ts IDs restart when the ts server does, so the newest matching entry wins. Entries without
    a ``local_id`` predate the current history format and are skipped.
    """
    history = load_history()
    for entry in reversed(history):
        if "local_id" in entry and job_id(entry) == id:
            return entry
    return None


def mark_stopped(local_id: int):
    """Flag a history entry as user-stopped, so ``jobs`` can show it distinctly."""
    history = load_history()
    for entry in history:
        if entry.get("local_id") == local_id:
            entry["stopped"] = True
    save_history(history)


def mark_job_time(local_id: int, *, started_at: float | None = None, ended_at: float | None = None):
    """Record start/end timestamps for a job, without overwriting ones already set.

    Neither the queue nor docker exposes exact start/end timestamps cheaply, so these
    are stamped lazily the first time a command happens to observe the job in that
    state (see ``manage.py``).
    """
    history = load_history()
    changed = False
    for entry in history:
        if entry.get("local_id") != local_id:
            continue
        if started_at is not None and "started_at" not in entry:
            entry["started_at"] = started_at
            changed = True
        if ended_at is not None and "ended_at" not in entry:
            entry["ended_at"] = ended_at
            changed = True
    if changed:
        save_history(history)


def execute_history(config: DockerConfig):
    """Show history of past Docker runs."""
    history_file = cli_config.history_path
    if not history_file.exists():
        typer.echo(f"No history found in '{history_file}'. You might not have submitted any jobs yet.")
        return

    history = load_history()

    table = Table(title="Docker Run History", show_lines=True)
    table.add_column("Job ID", justify="right", style="bold")
    table.add_column("Host")
    table.add_column("Timestamp")
    table.add_column("Branch")
    table.add_column("GPU(s)")
    table.add_column("Volume(s)")
    table.add_column("Imagename")
    table.add_column("Commands")

    for entry in history:
        shown_id = job_id(entry)
        shown_id = str(shown_id) if shown_id is not None else "-"
        host = entry.get("host") or "-"
        timestamp = datetime.fromtimestamp(entry["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
        _config = entry["config"]
        branch = _config.get("branch") or "-"
        gpus = _config["gpus"] if _config["gpus"] else "-"
        volumes = (
            "\n".join(
                [f"{v['hostpath']}:{v['containerpath']}:{v['permissions']}" for v in (_config.get("volumes") or [])]
            )
            or "-"
        )
        imagename = _config["imagename"]
        cmds = _config.get("commands") or _config.get("arguments") or []
        commands_str = " ".join(cmds)
        table.add_row(shown_id, host, timestamp, branch, gpus, volumes, imagename, Text(commands_str))

    Console().print(table)
