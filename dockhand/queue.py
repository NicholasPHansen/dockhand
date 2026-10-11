"""Task spooler (ts) queue integration."""

import re
from datetime import datetime

from dockhand.client.base import Client


def ts_submit(client: Client, docker_cmd: str, cwd: str, slots: int = 1) -> int:
    """Submit a docker command to task spooler. Returns the ts job ID."""
    slots_flag = f"-N {slots} " if slots > 1 else ""
    returncode, stdout = client.run(f"tsp {slots_flag}{docker_cmd}", cwd=cwd, capture=True)
    if returncode != 0:
        from dockhand.error import error_and_exit

        error_and_exit("Failed to submit job to task spooler. Is 'tsp' installed on the host?")
    try:
        return int(stdout.strip())
    except ValueError:
        from dockhand.error import error_and_exit

        error_and_exit(f"Unexpected output from task spooler: {stdout.strip()!r}")


def ts_list(client: Client, cwd: str) -> list[dict]:
    """List all task spooler jobs. Returns a list of parsed job dicts."""
    returncode, stdout = client.run("tsp -l", cwd=cwd, capture=True)
    if returncode != 0:
        return []
    return _parse_ts_list(stdout)


def ts_make_urgent(client: Client, job_id: int, cwd: str) -> bool:
    """Move a queued job to the front of the queue. Returns True on success."""
    returncode, _ = client.run(f"tsp -u {job_id}", cwd=cwd, capture=True)
    return returncode == 0


def ts_remove(client: Client, job_id: int, cwd: str) -> bool:
    """Remove a pending job from the queue. Returns True on success."""
    returncode, _ = client.run(f"tsp -r {job_id}", cwd=cwd, capture=True)
    return returncode == 0


def ts_kill(client: Client, job_id: int, cwd: str) -> bool:
    """Send SIGTERM to a running job. Returns True on success."""
    returncode, _ = client.run(f"tsp -k {job_id}", cwd=cwd, capture=True)
    return returncode == 0


def ts_get_job(client: Client, job_id: int, cwd: str) -> dict | None:
    """Look up a single job by ID from ts -l. Returns None if not found."""
    jobs = ts_list(client, cwd=cwd)
    return next((j for j in jobs if j["id"] == job_id), None)


_RUN_SLOTS_RE = re.compile(r"\[run=(\d+)/(\d+)\]")


def ts_slot_usage(client: Client, cwd: str) -> tuple[int, int] | None:
    """(slots in use, total slots) for the host's task spooler, from the `[run=N/M]` that
    `tsp -l` prints in its header line. None if it can't be read."""
    returncode, stdout = client.run("tsp -l | head -n 1", cwd=cwd, capture=True)
    match = _RUN_SLOTS_RE.search(stdout) if returncode == 0 else None
    return (int(match.group(1)), int(match.group(2))) if match else None


def extract_docker_command(input_string):
    # Regex breakdown:
    # -v\s+\S+:\S+:\w+  -> Matches the -v flag and the path mapping
    # .* -> Greedily matches as much as possible to find the LAST -v
    # \s+\S+            -> Matches the image name
    # \s+(.*)           -> Captures everything after that image name
    pattern = r".*-v\s+\S+:\S+:\w+\s+\S+\s+(.*)"
    match = re.search(pattern, input_string)

    if match:
        return match.group(1).strip()
    else:
        return None


# Matches the "real/user/sys" Times(r/u/s) field ts prints for finished jobs, e.g.
# "25851.03/2.62/3.05". Only real (wall-clock) seconds are kept. Searched for rather than
# read off a fixed column: ts pads this field with spaces rather than "-/-/-" placeholders
# while a job is still running/queued, which shifts the column count under a positional split.
_TIMES_RE = re.compile(r"(\d+\.\d+)/\d+\.\d+/\d+\.\d+")

# The image is the token right after the last `-v host:container:perm` mount (same anchor
# as extract_docker_command); the container name is dockhand's `--name dockhand-<local_id>`.
_IMAGE_RE = re.compile(r".*-v\s+\S+:\S+:\w+\s+(\S+)")
_NAME_RE = re.compile(r"--name\s+(\S+)")


def _parse_ts_list(output: str) -> list[dict]:
    """Parse ts -l output into a list of dicts.

    Expected format (header line followed by job lines):
        ID   State      Output               E-Level  Times(r/u/s)   Command [run=N/M]
        0    finished   /tmp/ts-out.XXX      0        0.1/0.0/0.0    docker run ...
        1    running    /tmp/ts-out.YYY                              docker run ...
        2    queued     (file)                                       docker run ...
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
        command = extract_docker_command(line)
        if len(parts) < 2:
            continue
        try:
            job_id = int(parts[0])
        except ValueError:
            continue
        times_match = _TIMES_RE.search(line)
        image_match = _IMAGE_RE.match(line)
        name_match = _NAME_RE.search(line)
        jobs.append(
            {
                "id": job_id,
                "state": parts[1],  # queued / running / finished / failed / skipped
                "output_file": parts[2] if len(parts) > 2 else None,
                "exit_code": parts[3] if len(parts) > 3 else None,
                # Authoritative wall-clock duration from ts itself, once the job has
                # finished — exact regardless of when this was observed.
                "duration_seconds": float(times_match.group(1)) if times_match else None,
                "command": command if command else "",
                "image": image_match.group(1) if image_match else None,
                "container_name": name_match.group(1) if name_match else None,
            }
        )

    return jobs


def ts_job_info(client: Client, job_ids: list[int], cwd: str) -> dict[int, dict]:
    """Per-job details that only `tsp -i` has, for every job in one round trip:
    ``{"slots": N, "started": epoch_seconds}``.

    ``slots`` is what the job reserved (`tsp -N`, "Slots required: 16"). ``started`` is only
    present once a job has started: `tsp -i` prints it in the host's local time ("Start time:
    Sat Oct 10 07:18:53 2026"), so the host's UTC offset is fetched alongside to convert it.
    """
    if not job_ids:
        return {}
    loop = "; ".join(f"echo @@{i}; tsp -i {i} | grep -E '^(Start time|Slots required):'" for i in job_ids)
    # `; true`: grep's exit status for the last job would otherwise become the command's.
    returncode, stdout = client.run(f"date +%z; {loop}; true", cwd=cwd, capture=True)
    lines = stdout.strip().split("\n")
    if returncode != 0 or not lines:
        return {}
    try:
        host_tz = datetime.strptime(lines[0].strip(), "%z").tzinfo
    except ValueError:
        return {}

    info: dict[int, dict] = {}
    current = None
    for line in lines[1:]:
        if line.startswith("@@"):
            current = int(line[2:])
            info[current] = {}
        elif current is None:
            continue
        elif line.startswith("Slots required:"):
            try:
                info[current]["slots"] = int(line.removeprefix("Slots required:"))
            except ValueError:
                pass
        elif line.startswith("Start time:"):
            # ctime pads single-digit days ("Sep  7"); collapse whitespace before parsing.
            text = " ".join(line.removeprefix("Start time:").split())
            try:
                started = datetime.strptime(text, "%a %b %d %H:%M:%S %Y").replace(tzinfo=host_tz)
                info[current]["started"] = started.timestamp()
            except ValueError:
                pass
    return info
