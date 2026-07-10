"""Docker container submission and queuing."""
from typing import List

import typer
from git import InvalidGitRepositoryError, Repo
from rich.progress import Progress, SpinnerColumn, TextColumn

from dockhand.client import get_client
from dockhand.config import DockerConfig, cli_config
from dockhand.history import add_to_history
from dockhand.sync import execute_sync


def _build_docker_run_cmd(
    config: DockerConfig,
    commands: List[str],
    imagename: str,
    gpus: str | None,
    effective_ports: list[str] | None,
    mount_code: bool = True,
    run_flags: list[str] | None = None,
) -> str:
    """Build the docker run command string.

    When ``mount_code`` is True (mount delivery) the project directory is bind-mounted
    over ``containerworkdir`` and ``preserve_paths`` anonymous volumes are layered on
    top. When False (bake delivery) the code is already baked into ``imagename``, so no
    code mount or preserve volumes are emitted — only data volumes.
    """
    code_mounts = []
    if mount_code:
        if config.containerworkdir == "/":
            typer.echo(
                "Warning: containerworkdir is '/' — mounting code at the container root "
                "will shadow the entire filesystem.",
                err=True,
            )
        # Implicit code mount: remote project path → containerworkdir
        code_mounts.append(f"-v {cli_config.remote_path}:{config.containerworkdir}:rw")

        # Anonymous volumes layered on top of the code mount for paths that must keep the
        # image's build-time contents (e.g. a virtualenv or node_modules baked in at build
        # time) instead of being shadowed by the bind-mounted host project directory.
        workdir = config.containerworkdir.rstrip("/")
        code_mounts += [f"-v {workdir}/{path.strip('/')}" for path in config.preserve_paths]

    data_volumes = []
    if config.volumes is not None:
        data_volumes = [f"-v {v['hostpath']}:{v['containerpath']}:{v['permissions']}" for v in config.volumes]

    gpu_flags = [f"--gpus {gpus}"] if gpus is not None else []
    port_flags = [f"-p {mapping}" for mapping in effective_ports] if effective_ports is not None else []

    # Run flags come from the transport (e.g. ["--rm"] for the queue, or
    # ["-d", "--name", ...] for a detached direct run).
    run_flags = ["--rm"] if run_flags is None else run_flags

    return " ".join(
        [
            "docker",
            "run",
            *run_flags,
            *code_mounts,
            *data_volumes,
            *gpu_flags,
            *port_flags,
            imagename,
            *commands,
        ]
    )


def _get_branch() -> str | None:
    try:
        with Repo(cli_config.project_root) as repo:
            return repo.active_branch.name
    except (InvalidGitRepositoryError, Exception):
        return None


def execute_submit(
    config: DockerConfig,
    commands: List[str],
    sync: bool,
    imagename: str | None = None,
    gpus: str | None = None,
    ports: list[str] | None = None,
    urgent: bool = False,
    slots: int | None = None,
    image_ref: str | None = None,
) -> int:
    """Optionally sync code, then start a container run. Returns the local job ID.

    Runs through the queue (task spooler) when ``queue.enabled``, otherwise starts a
    detached container directly. When ``image_ref`` is given (e.g. resubmitting a baked
    job), that exact pre-built image is run verbatim — no re-resolution and no rebuild.
    """
    from dockhand.build import execute_build
    from dockhand.history import reserve_local_id
    from dockhand.tagging import resolve_image_ref
    from dockhand.transport import get_transport

    if sync:
        execute_sync(confirm_changes=True)

    imagename = imagename or config.imagename
    gpus = gpus if gpus is not None else config.gpus
    effective_ports = ports if ports is not None else config.ports
    effective_slots = slots if slots is not None else cli_config.queue.slots

    transport = get_transport()
    local_id = reserve_local_id()

    if image_ref is not None:
        # Rerun an exact pre-built image (baked); no re-resolution, no rebuild.
        run_image = image_ref
        mount_code = False
    else:
        delivery = config.resolve_code_delivery(cli_config.queue.enabled)
        if delivery == "bake":
            # Bake the code into an image and run that; no code mount at run time. Queued
            # jobs get an immutable per-submit tag so they stay pinned to their code.
            run_image = resolve_image_ref(imagename, unique=cli_config.queue.enabled)
            execute_build(config, sync=False, dockerfile=config.dockerfile, imagename=run_image)
            mount_code = False
        else:
            run_image = imagename
            mount_code = True

    docker_cmd = _build_docker_run_cmd(
        config,
        commands,
        run_image,
        gpus,
        effective_ports,
        mount_code=mount_code,
        run_flags=transport.run_flags(local_id),
    )

    with get_client() as client:
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task(description="Submitting job", total=None)
            handle = transport.submit(
                client, docker_cmd, local_id=local_id, slots=effective_slots, urgent=urgent
            )
            progress.update(task, completed=True)

    host = cli_config.ssh.hostname if cli_config.ssh else "localhost"
    add_to_history(
        config,
        commands=commands,
        local_id=local_id,
        handle=handle,
        image_ref=run_image,
        branch=_get_branch(),
        ports=effective_ports,
        host=host,
    )

    verb = "Queued" if cli_config.queue.enabled else "Started"
    label = "urgent job" if (urgent and cli_config.queue.enabled) else "job"
    typer.echo(f"{verb} {label} #{local_id}")
    return local_id
