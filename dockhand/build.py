"""Docker image building."""
from rich.progress import Progress, SpinnerColumn, TextColumn

from dockhand.client import get_client
from dockhand.config import DockerConfig, cli_config
from dockhand.error import error_and_exit
from dockhand.sync import execute_sync


def execute_build(
    config: DockerConfig,
    sync: bool,
    dockerfile: str | None = None,
    imagename: str | None = None,
    verbose: bool = False,
):
    """Build the Docker image."""
    if sync:
        execute_sync(confirm_changes=True)

    dockerfile = dockerfile or config.dockerfile
    imagename = imagename or config.imagename
    cmd = f"docker build -f {dockerfile} -t {imagename} ."

    with get_client() as client:
        if verbose:
            returncode, _ = client.run(cmd, cwd=cli_config.remote_path, capture=False)
        else:
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
                task = progress.add_task(description="Building image", total=None)
                returncode, _ = client.run(cmd, cwd=cli_config.remote_path, capture=True)
                progress.update(task, completed=True)

    if returncode != 0:
        error_and_exit(f"Build command failed with return code {returncode}.")
