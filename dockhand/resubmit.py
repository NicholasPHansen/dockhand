"""Docker container resubmission."""
import dataclasses

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

    execute_submit(updated_config, commands, sync=False, imagename=imagename, gpus=gpus)
