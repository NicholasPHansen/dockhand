"""SSH local port forwarding to docker container ports."""
import time
from contextlib import ExitStack

import fabric
import typer

from dockhand.config import cli_config
from dockhand.error import error_and_exit
from dockhand.history import load_history


def execute_tunnel(*, container_id: str | None, ports: list[str] | None):
    """Forward ports to localhost via SSH tunnel.

    If ports are provided, use those. Otherwise read from the last (or specified) history entry.
    """
    # Resolve port list: explicit override takes priority over history
    if ports:
        effective_ports = ports
    else:
        history = load_history()
        if not history:
            error_and_exit("No container history found. Run a container first.")

        if container_id is not None:
            entry = next((e for e in history if e["container_id"] == container_id), None)
            if entry is None:
                error_and_exit(f"Container ID '{container_id}' not found in history.")
        else:
            entry = history[-1]

        effective_ports = entry["config"].get("ports") or []
        if not effective_ports:
            error_and_exit("No port mappings in history. Use -p to specify ports explicitly.")

    # Parse "hostPort:containerPort" → forward local hostPort to remote hostPort
    host_ports = []
    for mapping in effective_ports:
        parts = mapping.split(":")
        if len(parts) != 2:
            error_and_exit(f"Unexpected port mapping format: '{mapping}'. Expected 'hostPort:containerPort'.")
        host_ports.append(int(parts[0]))

    ssh = cli_config.ssh
    conn = fabric.Connection(
        host=ssh.hostname,
        user=ssh.user,
        connect_kwargs={"key_filename": ssh.identityfile},
    )

    typer.echo(f"Forwarding ports: {', '.join(str(p) for p in host_ports)}")
    typer.echo("Press Ctrl+C to stop the tunnel.")

    with ExitStack() as stack:
        for port in host_ports:
            stack.enter_context(conn.forward_local(port, remote_host="localhost", remote_port=port))
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            typer.echo("\nTunnel closed.")
