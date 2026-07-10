"""Docker container resubmission."""
import dataclasses

import typer

from dockhand.config import DockerConfig, DockerResubmitConfig
from dockhand.error import error_and_exit


def execute_resubmit(docker_config: DockerConfig, resubmit_config: DockerResubmitConfig):
    """Resubmit a previous docker run with optional overrides."""
    from dockhand.history import get_history_entry, load_history
    from dockhand.submit import execute_submit

    history = load_history()

    if not history:
        error_and_exit("No docker history found. Submit a docker job first.")

    local_id = int(resubmit_config.container_id) if resubmit_config.container_id else None
    if local_id is not None:
        entry = get_history_entry(local_id)
        if entry is None:
            error_and_exit(f"Job #{local_id} not found in history.")
    else:
        entry = history[-1]

    original_config = entry["config"]

    commands = resubmit_config.commands if resubmit_config.commands is not None else original_config.get("commands", [])
    imagename = resubmit_config.imagename if resubmit_config.imagename is not None else original_config.get("imagename")
    gpus = resubmit_config.gpus if resubmit_config.gpus is not None else original_config.get("gpus")

    updated_config = dataclasses.replace(docker_config, imagename=imagename, gpus=gpus)

    # Reproduce a baked job verbatim: rerun the exact image it originally built instead of
    # re-resolving/rebuilding from the current code. Only when the original ran a distinct
    # baked tag and the image name wasn't overridden.
    original_image_ref = original_config.get("image_ref")
    original_imagename = original_config.get("imagename")
    pin_image = (
        original_image_ref
        if (resubmit_config.imagename is None and original_image_ref and original_image_ref != original_imagename)
        else None
    )
    if pin_image is not None:
        typer.echo(f"Reusing baked image {pin_image} from the original run.")

    execute_submit(updated_config, commands, sync=False, imagename=imagename, gpus=gpus, image_ref=pin_image)
