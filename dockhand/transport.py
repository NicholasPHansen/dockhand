"""Execution transports: task-spooler queue vs. direct ``docker run``.

When ``queue.enabled`` is true, jobs are submitted to task spooler (``tsp``) and run
in submission order. When it is false there is no queue, so jobs are started
immediately as detached containers (``docker run -d``) and managed directly with
``docker logs``/``stop``/``ps``/``rm``.

Both backends expose the same interface so ``submit`` and the management commands
(``logs``/``stop``/``jobs``/``remove``) don't care which is active. A job's transport
is recorded in history, so per-job commands dispatch to the backend that created it.
"""
from abc import ABC, abstractmethod

import typer

from dockhand.client.base import Client
from dockhand.config import cli_config
from dockhand.error import error_and_exit
from dockhand.queue import ts_get_job, ts_kill, ts_list, ts_make_urgent, ts_remove, ts_submit


def _container_name(local_id: int) -> str:
    return f"dockhand-{local_id}"


def get_transport() -> "Transport":
    """Select the transport for a new submission based on ``queue.enabled``."""
    return TaskSpoolerTransport() if cli_config.queue.enabled else DockerTransport()


def transport_for_entry(entry: dict) -> "Transport":
    """Select the transport that created an existing history entry.

    Old entries predate the ``transport`` field and were always task spooler.
    """
    name = entry.get("transport", TaskSpoolerTransport.name)
    return _TRANSPORTS.get(name, TaskSpoolerTransport())


def entry_handle(entry: dict):
    """The backend handle for an entry (tsp job id, or container name)."""
    return entry.get("handle", entry.get("ts_job_id"))


class Transport(ABC):
    name: str

    @abstractmethod
    def run_flags(self, local_id: int) -> list[str]:
        """Flags injected right after ``docker run`` (e.g. ``--rm`` or ``-d --name``)."""

    @abstractmethod
    def submit(self, client: Client, docker_cmd: str, *, local_id: int, slots: int, urgent: bool) -> dict:
        """Start the job. Returns a handle dict merged into the history entry."""

    @abstractmethod
    def list_jobs(self, client: Client) -> list[dict]:
        """Live jobs as dicts: ``{handle, state, command}`` (states normalized)."""

    @abstractmethod
    def logs(self, client: Client, entry: dict, *, n: int | None, follow: bool) -> int:
        """Stream a job's logs. Returns the command's exit code."""

    @abstractmethod
    def stop(self, client: Client, entry: dict) -> bool:
        """Stop a running job."""

    @abstractmethod
    def remove(self, client: Client, entry: dict) -> bool:
        """Remove a job that hasn't started (queued) / clean up its container."""


class TaskSpoolerTransport(Transport):
    name = "task_spooler"

    def run_flags(self, local_id: int) -> list[str]:
        return ["--rm"]

    def submit(self, client, docker_cmd, *, local_id, slots, urgent):
        job_id = ts_submit(client, docker_cmd, cwd=cli_config.remote_path, slots=slots)
        if urgent:
            ts_make_urgent(client, job_id, cwd=cli_config.remote_path)
        return {"transport": self.name, "handle": job_id, "ts_job_id": job_id}

    def list_jobs(self, client):
        jobs = ts_list(client, cwd=cli_config.remote_path)
        return [{"handle": j["id"], "state": j["state"], "command": j["command"]} for j in jobs]

    def logs(self, client, entry, *, n, follow):
        job_id = entry_handle(entry)
        if follow:
            cmd = f"tail -f $(tsp -o {job_id})"
        elif n is not None:
            cmd = f"tail -n {n} $(tsp -o {job_id})"
        else:
            cmd = f"cat $(tsp -o {job_id})"
        returncode, _ = client.run(cmd, cwd=cli_config.remote_path)
        return returncode

    def stop(self, client, entry):
        job_id = entry_handle(entry)
        job = ts_get_job(client, job_id, cwd=cli_config.remote_path)
        if job is None:
            error_and_exit(f"Job (tsp {job_id}) not found in task spooler.")
        if job["state"] != "running":
            error_and_exit(f"Job is not running (state: {job['state']}). Use 'remove' for queued jobs.")
        return ts_kill(client, job_id, cwd=cli_config.remote_path)

    def remove(self, client, entry):
        job_id = entry_handle(entry)
        job = ts_get_job(client, job_id, cwd=cli_config.remote_path)
        if job and job["state"] != "queued":
            error_and_exit(f"Job is not queued (state: {job['state']}). Use 'stop' to terminate running jobs.")
        return ts_remove(client, job_id, cwd=cli_config.remote_path)


# docker container State → the queue-style state labels the UI already knows.
_DOCKER_STATE_MAP = {
    "running": "running",
    "created": "queued",
    "restarting": "running",
    "paused": "running",
    "exited": "finished",
    "dead": "failed",
    "removing": "finished",
}


class DockerTransport(Transport):
    name = "docker"

    def run_flags(self, local_id: int) -> list[str]:
        # Detached, named, and NOT --rm so logs survive after the container exits.
        return ["-d", "--name", _container_name(local_id)]

    def submit(self, client, docker_cmd, *, local_id, slots, urgent):
        if urgent:
            typer.echo("Warning: --urgent has no effect without a queue.", err=True)
        returncode, _ = client.run(docker_cmd, cwd=cli_config.remote_path, capture=True)
        if returncode != 0:
            error_and_exit(f"docker run failed (exit {returncode}).")
        return {"transport": self.name, "handle": _container_name(local_id)}

    def list_jobs(self, client):
        fmt = "{{.Names}}\t{{.State}}\t{{.Command}}"
        returncode, stdout = client.run(
            f"docker ps -a --filter name=dockhand- --format '{fmt}'", cwd=cli_config.remote_path, capture=True
        )
        if returncode != 0:
            return []
        jobs = []
        for line in stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            name, state = parts[0], parts[1]
            command = parts[2].strip('"') if len(parts) > 2 else ""
            jobs.append({"handle": name, "state": _DOCKER_STATE_MAP.get(state, state), "command": command})
        return jobs

    def logs(self, client, entry, *, n, follow):
        name = entry_handle(entry)
        flags = []
        if follow:
            flags.append("-f")
        if n is not None:
            flags.append(f"--tail {n}")
        cmd = f"docker logs {' '.join(flags)} {name}".replace("  ", " ")
        returncode, _ = client.run(cmd, cwd=cli_config.remote_path)
        return returncode

    def stop(self, client, entry):
        name = entry_handle(entry)
        returncode, _ = client.run(f"docker stop {name}", cwd=cli_config.remote_path, capture=True)
        return returncode == 0

    def remove(self, client, entry):
        # No queue to dequeue from — remove the container record (force-remove if running).
        name = entry_handle(entry)
        returncode, _ = client.run(f"docker rm -f {name}", cwd=cli_config.remote_path, capture=True)
        return returncode == 0


_TRANSPORTS = {
    TaskSpoolerTransport.name: TaskSpoolerTransport(),
    DockerTransport.name: DockerTransport(),
}
