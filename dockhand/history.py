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
    container_id: str,
    commands: List[str],
    branch: str | None = None,
    ports: list[str] | None = None,
    host: str | None = None,
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
    history.append(entry)
    save_history(history)


def execute_history(config: DockerConfig):
    """Show history of past Docker runs."""
    if not DOCKER_HISTORY_FILE.exists():
        typer.echo(f"No history found in '{DOCKER_HISTORY_FILE}'. You might not have submitted any jobs yet.")
        return

    history = load_history()

    table = Table(title="Docker Run Commands", show_lines=True)
    table.add_column("Timestamp")
    table.add_column("Container ID(s)")
    table.add_column("Host")
    table.add_column("Branch")
    table.add_column("Dockerfile")
    table.add_column("GPU(s)")
    table.add_column("Volume(s)")
    table.add_column("Imagename")
    table.add_column("Commands")

    for entry in history:
        timestamp = datetime.fromtimestamp(entry["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
        container_id = entry["container_id"]
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
        table.add_row(str(timestamp), container_id, host, branch, dockerfile, gpus, volumes, imagename, commands_str)

    console = Console()
    console.print(table)
