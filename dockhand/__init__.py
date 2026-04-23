from typing import Annotated, List

import typer

from dockhand.build import execute_build
from dockhand.config import DockerResubmitConfig, cli_config
from dockhand.constants import CONFIG_FILENAME
from dockhand.download import execute_download
from dockhand.history import execute_history
from dockhand.manage import execute_logs, execute_remove, execute_stats, execute_stop
from dockhand.run import execute_resubmit, execute_run, execute_submit
from dockhand.tunnel import execute_tunnel
from dockhand.volumes import execute_volumes

__version__ = "0.1.0"

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
):
    """Build the image and run a container with the given command(s)."""
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
    )


@cli.command()
def run(
    commands: List[str],
    imagename: Annotated[str, typer.Option(default_factory=DockerDefault("imagename"))],
    gpus: Annotated[str, typer.Option(default_factory=DockerDefault("gpus"))],
    ports: Annotated[List[str], typer.Option("-p")] = [],
):
    """Run a container from an already-built image."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    execute_run(cli_config.docker, commands, imagename=imagename, gpus=gpus, ports=ports or None)


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
        typer.Argument(help="Job ID (queue mode) or container ID (direct mode). Defaults to last job/container."),
    ] = None,
    all: bool = False,
    n: int | None = None,
):
    """Show logs from a job or container (defaults to last)."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    if cli_config.queue.enabled:
        job_id = int(id) if id is not None else None
        execute_logs(cli_config.docker, job_id=job_id, container_id=None, imagename=imagename, all=all, n=n)
    else:
        execute_logs(cli_config.docker, job_id=None, container_id=id, imagename=imagename, all=all, n=n)


@cli.command()
def stop(
    id: Annotated[
        str | None,
        typer.Argument(help="Job ID (queue mode) or container ID (direct mode). Defaults to last job/container."),
    ] = None,
):
    """Stop a running job/container or remove a queued job (defaults to last)."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    if cli_config.queue.enabled:
        job_id = int(id) if id is not None else None
        execute_stop(cli_config.docker, job_id=job_id)
    else:
        execute_stop(cli_config.docker, container_id=id)


@cli.command()
def jobs():
    """List running containers (docker ps)."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    execute_stats(cli_config.docker)


@cli.command()
def history():
    """Show history of past Docker runs."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    execute_history(cli_config.docker)


@cli.command()
def volumes():
    """List files in docker-mounted volumes using workdir-relative paths."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    execute_volumes(cli_config.docker)


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
):
    """Download a file from a docker volume by its workdir-relative path.

    Files are downloaded preserving their directory structure relative to project root."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    if list_only:
        execute_volumes(cli_config.docker)
        return
    if path is None:
        typer.echo("Error: Missing argument 'PATH'. Use --list to see available files.")
        raise typer.Exit(1)
    execute_download(cli_config.docker, path=path, local_path=local_path)


@cli.command()
def resubmit(
    id: Annotated[
        str | None,
        typer.Argument(help="Job ID (queue mode) or container ID (direct mode). Defaults to last."),
    ] = None,
    commands: List[str] | None = None,
    dockerfile: str | None = None,
    imagename: str | None = None,
    gpus: str | None = None,
):
    """Resubmit a previous Docker run (defaults to latest). Optionally with new parameters."""
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
        typer.Argument(help="Job IDs (queue mode) or container IDs (direct mode). Defaults to last."),
    ] = None,
    from_history: bool = False,
):
    """Remove job(s) from queue or docker container(s) (defaults to last)."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    if cli_config.queue.enabled:
        job_ids = [int(i) for i in ids] if ids else None
        execute_remove(cli_config.docker, job_ids=job_ids, from_history=from_history)
    else:
        execute_remove(cli_config.docker, container_ids=ids, from_history=from_history)


@cli.command()
def tunnel(
    container_id: str | None = None,
    ports: Annotated[List[str], typer.Option("-p")] = [],
):
    """Forward docker container ports to localhost via SSH tunnel.

    Defaults to ports from the last (or specified) run. Use -p to override."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    execute_tunnel(container_id=container_id, ports=ports or None)


if __name__ == "__main__":
    cli()
