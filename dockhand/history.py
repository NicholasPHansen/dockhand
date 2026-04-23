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

DOCKER_HISTORY_FILE = Path(".dockhand_history.json")


def load_history() -> list[dict]:
    """Load container run history from disk."""
    path = DOCKER_HISTORY_FILE
    if not path.exists():
        return []
    return json.loads(path.read_text())


def save_history(history: list[dict]):
    """Save container run history to disk."""
    path = DOCKER_HISTORY_FILE
    path.write_text(json.dumps(history))


def add_to_history(
    config: DockerConfig,
    container_id: str | None,
    commands: List[str],
    branch: str | None = None,
    ports: list[str] | None = None,
    host: str | None = None,
    ts_job_id: int | None = None,
):
    """Add a container run to the history file."""
    history = load_history()
    _d = {
        "dockerfile": config.dockerfile,
        "gpus": config.gpus,
        "volumes": config.volumes,
        "imagename": config.imagename,
        "commands": commands,
        "ports": ports,
    }
    if branch is not None:
        _d["branch"] = branch
    entry = {"config": _d, "container_id": container_id, "timestamp": time.time()}
    if host is not None:
        entry["host"] = host
    if ts_job_id is not None:
        entry["ts_job_id"] = ts_job_id
    history.append(entry)
    save_history(history)


def get_history_entry_by_job_id(ts_job_id: int) -> dict | None:
    """Look up the most recent history entry with a given ts job ID."""
    history = load_history()
    for entry in reversed(history):
        if entry.get("ts_job_id") == ts_job_id:
            return entry
    return None


def execute_history(config: DockerConfig):
    """Show history of past Docker runs."""
    if not DOCKER_HISTORY_FILE.exists():
        typer.echo(f"No history found in '{DOCKER_HISTORY_FILE}'. You might not have submitted any jobs yet.")
        return

    history = load_history()

    has_job_ids = any("ts_job_id" in entry for entry in history)

    table = Table(title="Docker Run Commands", show_lines=True)
    table.add_column("Timestamp")
    if has_job_ids:
        table.add_column("Job ID")
    table.add_column("Container ID")
    table.add_column("Host")
    table.add_column("Branch")
    table.add_column("Dockerfile")
    table.add_column("GPU(s)")
    table.add_column("Volume(s)")
    table.add_column("Imagename")
    table.add_column("Commands")

    for entry in history:
        timestamp = datetime.fromtimestamp(entry["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
        container_id = entry.get("container_id") or "-"
        host = entry.get("host") or "-"
        _config = entry["config"]
        branch = _config.get("branch") or "-"
        dockerfile = _config["dockerfile"]
        gpus = _config["gpus"] if _config["gpus"] else "-"
        volumes = "\n".join([f"{v['hostpath']}:{v['containerpath']}:{v['permissions']}" for v in _config["volumes"]])
        imagename = _config["imagename"]
        # support both old "arguments" key and new "commands" key
        cmds = _config.get("commands") or _config.get("arguments") or []
        commands_str = " ".join(cmds)
        row = [str(timestamp)]
        if has_job_ids:
            row.append(str(entry.get("ts_job_id", "-")))
        row.extend([container_id, host, branch, dockerfile, gpus, volumes, imagename, commands_str])
        table.add_row(*row)

    console = Console()
    console.print(table)
