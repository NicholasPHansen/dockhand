from typing import Annotated, List

import typer

from dockhand.build import execute_build
from dockhand.client import get_client
from dockhand.config import DockerResubmitConfig, cli_config
from dockhand.constants import CONFIG_FILENAME
from dockhand.download import execute_download
from dockhand.history import execute_history
from dockhand.manage import execute_logs, execute_remove, execute_stats, execute_stop
from dockhand.queue import ts_make_urgent
from dockhand.run import execute_queued_run, execute_resubmit, execute_submit
from dockhand.tunnel import execute_tunnel
from dockhand.volumes import execute_volumes

__version__ = "0.2.0"

cli = typer.Typer(pretty_exceptions_show_locals=False)


class DockerDefault:
    def __init__(self, key: str):
        self.key = key

    def __call__(self):
        return getattr(cli_config.docker, self.key, None)

    def __str__(self):
        value = getattr(cli_config.docker, self.key, None)
        return str(value)


class SyncDefault:
    def __call__(self):
        return cli_config.sync

    def __str__(self):
        return str(cli_config.sync)


def profile_callback(profile: str | None):
    if profile is not None:
        cli_config.load_profile(profile)


def version_callback(value: bool):
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@cli.callback()
def main(
    profile: Annotated[
        str, typer.Option("--profile", callback=profile_callback, help="Optional profile from config.")
    ] = None,
    version: Annotated[bool, typer.Option("--version", callback=version_callback)] = False,
):
    pass


@cli.command()
def submit(
    commands: List[str],
    dockerfile: Annotated[str, typer.Option(default_factory=DockerDefault("dockerfile"))],
    imagename: Annotated[str, typer.Option(default_factory=DockerDefault("imagename"))],
    gpus: Annotated[str, typer.Option(default_factory=DockerDefault("gpus"))],
    sync: Annotated[bool, typer.Option(default_factory=SyncDefault())],
    ports: Annotated[List[str], typer.Option("-p")] = [],
    urgent: Annotated[bool, typer.Option("--urgent", help="Move to front of queue.")] = False,
):
    """Build the image and queue a container run with the given command(s)."""
    msg = f"docker requires a Docker configuration in '{CONFIG_FILENAME}'"
    cli_config.check_docker(msg=msg)
    execute_submit(
        cli_config.docker,
        commands,
        sync=sync,
        dockerfile=dockerfile,
        imagename=imagename,
        gpus=gpus,
        ports=ports or None,
        urgent=urgent,
    )


@cli.command()
def run(
    commands: List[str],
    imagename: Annotated[str, typer.Option(default_factory=DockerDefault("imagename"))],
    gpus: Annotated[str, typer.Option(default_factory=DockerDefault("gpus"))],
    ports: Annotated[List[str], typer.Option("-p")] = [],
    urgent: Annotated[bool, typer.Option("--urgent", help="Move to front of queue.")] = False,
):
    """Queue a container run from an already-built image."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    execute_queued_run(
        cli_config.docker, commands, imagename=imagename, gpus=gpus, ports=ports or None, urgent=urgent
    )


@cli.command()
def install(
    dockerfile: Annotated[str, typer.Option(default_factory=DockerDefault("dockerfile"))],
    imagename: Annotated[str, typer.Option(default_factory=DockerDefault("imagename"))],
    sync: Annotated[bool, typer.Option(default_factory=SyncDefault())],
):
    """Install (build) the Docker image."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    execute_build(cli_config.docker, sync=sync, dockerfile=dockerfile, imagename=imagename)


@cli.command()
def logs(
    imagename: Annotated[str, typer.Option(default_factory=DockerDefault("imagename"))],
    id: Annotated[
        str | None,
        typer.Argument(help="Job ID. Defaults to last job."),
    ] = None,
    all: bool = False,
    n: int | None = None,
):
    """Show logs from a job (defaults to last)."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    job_id = int(id) if id is not None else None
    execute_logs(cli_config.docker, job_id=job_id, container_id=None, imagename=imagename, all=all, n=n)


@cli.command()
def stop(
    id: Annotated[
        str | None,
        typer.Argument(help="Job ID. Defaults to last job."),
    ] = None,
):
    """Stop a running job or remove a queued job (defaults to last)."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    job_id = int(id) if id is not None else None
    execute_stop(cli_config.docker, job_id=job_id)


@cli.command()
def jobs():
    """List all jobs in the queue."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    execute_stats(cli_config.docker)


@cli.command()
def urgent(
    id: Annotated[
        str | None,
        typer.Argument(help="Job ID to promote to the front of the queue. Defaults to last job."),
    ] = None,
):
    """Promote a queued job to the front of the queue."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    if id is None:
        from dockhand.history import load_history

        history = load_history()
        queued = [e for e in history if e.get("ts_job_id") is not None]
        if not queued:
            typer.echo("No job history found. Provide a job ID.")
            raise typer.Exit(1)
        job_id = queued[-1]["ts_job_id"]
    else:
        job_id = int(id)

    with get_client() as client:
        if ts_make_urgent(client, job_id, cwd=cli_config.remote_path):
            typer.echo(f"Job {job_id} moved to front of queue.")
        else:
            typer.echo(f"Failed to promote job {job_id}. It may have already started or finished.")
            raise typer.Exit(1)


@cli.command()
def history():
    """Show history of past Docker runs."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    execute_history(cli_config.docker)


@cli.command()
def volumes(
    id: Annotated[
        str | None,
        typer.Argument(help="Job ID or container ID to use mounts from. Defaults to config."),
    ] = None,
    depth: Annotated[
        int | None,
        typer.Option("--depth", help="Maximum directory depth to display."),
    ] = None,
):
    """List the full container filesystem as a tree."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    imagename, override_volumes = _resolve_volumes_overrides(id)
    execute_volumes(cli_config.docker, depth=depth, imagename=imagename, volumes=override_volumes)


@cli.command()
def download(
    path: Annotated[
        str | None,
        typer.Argument(help="Workdir-relative path to download (as shown by volumes)"),
    ] = None,
    local_path: Annotated[
        str | None,
        typer.Option("--local-path", "-l", help="Local destination path (defaults to project root)"),
    ] = None,
    list_only: Annotated[
        bool,
        typer.Option("--list", help="List files in docker-mounted volumes (same as volumes)"),
    ] = False,
    depth: Annotated[
        int | None,
        typer.Option("--depth", help="Maximum directory depth to display (only applies with --list)."),
    ] = None,
    id: Annotated[
        str | None,
        typer.Option("--id", help="Job ID or container ID to use mounts from (only applies with --list)."),
    ] = None,
):
    """Download a file from a docker volume by its workdir-relative path.

    Files are downloaded preserving their directory structure relative to project root."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    if list_only:
        imagename, override_volumes = _resolve_volumes_overrides(id)
        execute_volumes(cli_config.docker, depth=depth, imagename=imagename, volumes=override_volumes)
        return
    if path is None:
        typer.echo("Error: Missing argument 'PATH'. Use --list to see available files.")
        raise typer.Exit(1)
    execute_download(cli_config.docker, path=path, local_path=local_path)


@cli.command()
def resubmit(
    id: Annotated[
        str | None,
        typer.Argument(help="Job ID to resubmit. Defaults to last."),
    ] = None,
    commands: List[str] | None = None,
    dockerfile: str | None = None,
    imagename: str | None = None,
    gpus: str | None = None,
):
    """Resubmit a previous job (defaults to latest). Optionally with new parameters."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    config = DockerResubmitConfig(
        container_id=id,
        commands=commands,
        dockerfile=dockerfile,
        imagename=imagename,
        gpus=gpus,
    )
    execute_resubmit(cli_config.docker, config)


@cli.command()
def remove(
    ids: Annotated[
        List[str],
        typer.Argument(help="Job IDs to remove from queue. Defaults to last."),
    ] = None,
    from_history: bool = False,
):
    """Remove pending job(s) from the queue (defaults to last)."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    job_ids = [int(i) for i in ids] if ids else None
    execute_remove(cli_config.docker, job_ids=job_ids, from_history=from_history)


@cli.command()
def tunnel(
    container_id: str | None = None,
    ports: Annotated[List[str], typer.Option("-p")] = [],
):
    """Forward docker container ports to localhost via SSH tunnel.

    Defaults to ports from the last (or specified) run. Use -p to override."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    execute_tunnel(container_id=container_id, ports=ports or None)


def _resolve_volumes_overrides(id: str | None) -> tuple[str | None, list | None]:
    """Look up imagename and volumes from history for a given job/container ID."""
    if id is None:
        return None, None
    from dockhand.history import get_history_entry

    entry = get_history_entry(id)
    if entry is None:
        typer.echo(f"Warning: ID '{id}' not found in history — using config defaults.")
        return None, None
    cfg = entry["config"]
    return cfg.get("imagename"), cfg.get("volumes")


if __name__ == "__main__":
    cli()
