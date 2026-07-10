"""Docker container run history management and tracking."""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import List

import typer
from rich.console import Console
from rich.table import Table

from dockhand.config import DockerConfig
from dockhand.constants import HISTORY_FILENAME

DOCKER_HISTORY_FILE = Path(".dockhand_history.json")


def load_history() -> list[dict]:
    """Load container run history from disk."""
    # path = DOCKER_HISTORY_FILE
    path = Path(HISTORY_FILENAME)
    if not path.exists():
        return []
    return json.loads(path.read_text())


def save_history(history: list[dict]):
    """Save container run history to disk."""
    # path = DOCKER_HISTORY_FILE
    path = Path(HISTORY_FILENAME)
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


def get_history_entry(local_id: int) -> dict | None:
    """Look up a history entry by local job ID."""
    history = load_history()
    for entry in reversed(history):
        if entry.get("local_id") == local_id:
            return entry
    return None


def execute_history(config: DockerConfig):
    """Show history of past Docker runs."""
    history_file = Path(HISTORY_FILENAME)
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
        local_id = str(entry.get("local_id", "-"))
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
        table.add_row(local_id, host, timestamp, branch, gpus, volumes, imagename, commands_str)

    Console().print(table)
