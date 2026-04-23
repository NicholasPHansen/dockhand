"""Task spooler (ts) queue integration."""
import re

from dockhand.client.base import Client


def ts_submit(client: Client, docker_cmd: str, cwd: str) -> int:
    """Submit a docker command to task spooler. Returns the ts job ID."""
    returncode, stdout = client.run(f"ts {docker_cmd}", cwd=cwd)
    if returncode != 0:
        from dockhand.error import error_and_exit

        error_and_exit("Failed to submit job to task spooler. Is 'ts' installed on the host?")
    try:
        return int(stdout.strip())
    except ValueError:
        from dockhand.error import error_and_exit

        error_and_exit(f"Unexpected output from task spooler: {stdout.strip()!r}")


def ts_list(client: Client, cwd: str) -> list[dict]:
    """List all task spooler jobs. Returns a list of parsed job dicts."""
    returncode, stdout = client.run("ts -l", cwd=cwd)
    if returncode != 0:
        return []
    return _parse_ts_list(stdout)


def ts_remove(client: Client, job_id: int, cwd: str) -> bool:
    """Remove a pending job from the queue. Returns True on success."""
    returncode, _ = client.run(f"ts -r {job_id}", cwd=cwd)
    return returncode == 0


def ts_kill(client: Client, job_id: int, cwd: str) -> bool:
    """Send SIGTERM to a running job. Returns True on success."""
    returncode, _ = client.run(f"ts -k {job_id}", cwd=cwd)
    return returncode == 0


def ts_get_container_id(client: Client, job_id: int, cwd: str) -> str | None:
    """Get the short (12-char) container ID from ts job output.

    docker run -d writes the full container ID to stdout, which ts captures.
    ts -o <id> returns the path to that output file.
    """
    returncode, stdout = client.run(f"cat $(ts -o {job_id})", cwd=cwd)
    if returncode != 0 or not stdout.strip():
        return None
    # docker run -d outputs a 64-char hex ID; take the first 12 chars
    container_id = stdout.strip()[:12]
    return container_id if len(container_id) == 12 else None


def ts_get_job(client: Client, job_id: int, cwd: str) -> dict | None:
    """Look up a single job by ID from ts -l. Returns None if not found."""
    jobs = ts_list(client, cwd=cwd)
    return next((j for j in jobs if j["id"] == job_id), None)


def _parse_ts_list(output: str) -> list[dict]:
    """Parse ts -l output into a list of dicts.

    Expected format (header line followed by job lines):
        ID   State      Output               E-Level  Times(r/u/s)   Command [run=N/M]
        0    finished   /tmp/ts-out.XXX      0        0.1/0.0/0.0    docker run ...
        1    running    /tmp/ts-out.YYY      -        -/-/-          docker run ...
        2    queued     (file)               -        -/-/-          docker run ...
    """
    jobs = []
    lines = output.strip().split("\n")
    if len(lines) < 2:
        return jobs

    for line in lines[1:]:  # skip header
        line = line.strip()
        if not line:
            continue
        # Split into at most 6 parts; the last part is the full command string
        parts = re.split(r"\s+", line, maxsplit=5)
        if len(parts) < 2:
            continue
        try:
            job_id = int(parts[0])
        except ValueError:
            continue
        jobs.append(
            {
                "id": job_id,
                "state": parts[1],  # queued / running / finished / failed / skipped
                "output_file": parts[2] if len(parts) > 2 else None,
                "exit_code": parts[3] if len(parts) > 3 else None,
                "command": parts[5] if len(parts) > 5 else "",
            }
        )

    return jobs
