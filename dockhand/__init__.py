from typing import Annotated, List

import typer

from dockhand.build import execute_build
from dockhand.config import DockerResubmitConfig, cli_config
from dockhand.constants import CONFIG_FILENAME
from dockhand.download import execute_download
from dockhand.history import execute_history
from dockhand.manage import execute_logs, execute_remove, execute_stats, execute_stop
from dockhand.run import execute_resubmit, execute_run, execute_submit
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
    sync: Annotated[bool, typer.Option(default_factory=DockerDefault("sync"))],
):
    """Build the image and run a container with the given command(s)."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    execute_submit(cli_config.docker, commands, sync=sync, dockerfile=dockerfile, imagename=imagename, gpus=gpus)


@cli.command()
def run(
    commands: List[str],
    imagename: Annotated[str, typer.Option(default_factory=DockerDefault("imagename"))],
    gpus: Annotated[str, typer.Option(default_factory=DockerDefault("gpus"))],
):
    """Run a container from an already-built image."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    execute_run(cli_config.docker, commands, imagename=imagename, gpus=gpus)


@cli.command()
def install(
    dockerfile: Annotated[str, typer.Option(default_factory=DockerDefault("dockerfile"))],
    imagename: Annotated[str, typer.Option(default_factory=DockerDefault("imagename"))],
    sync: Annotated[bool, typer.Option(default_factory=DockerDefault("sync"))],
):
    """Install (build) the Docker image."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    execute_build(cli_config.docker, sync=sync, dockerfile=dockerfile, imagename=imagename)


@cli.command()
def logs(
    imagename: Annotated[str, typer.Option(default_factory=DockerDefault("imagename"))],
    container_id: str | None = None,
    all: bool = False,
    n: int | None = None,
):
    """Show logs from a container (defaults to last run container)."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    execute_logs(cli_config.docker, container_id=container_id, imagename=imagename, all=all, n=n)


@cli.command()
def stop(container_id: str | None = None):
    """Stop a running container (defaults to last run container)."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    execute_stop(cli_config.docker, container_id=container_id)


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
    container_id: str | None = None,
    commands: List[str] | None = None,
    dockerfile: str | None = None,
    imagename: str | None = None,
    gpus: str | None = None,
):
    """Resubmit a previous Docker run (defaults to latest). Optionally with new parameters."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    config = DockerResubmitConfig(
        container_id=container_id,
        commands=commands,
        dockerfile=dockerfile,
        imagename=imagename,
        gpus=gpus,
    )
    execute_resubmit(cli_config.docker, config)


@cli.command()
def remove(
    container_ids: Annotated[List[str], typer.Argument()] = None,
    from_history: bool = False,
):
    """Remove container(s) (defaults to last run container). Optionally remove from history."""
    cli_config.check_docker(msg=f"docker requires a Docker configuration in '{CONFIG_FILENAME}'")
    execute_remove(cli_config.docker, container_ids=container_ids, from_history=from_history)


if __name__ == "__main__":
    cli()
