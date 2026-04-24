"""Docker volume inspection and path resolution."""

from rich.console import Console
from rich.tree import Tree

from dockhand.client import get_client
from dockhand.config import DockerConfig, cli_config

# Default scan depth when --depth is not specified.
# Keeps the find command fast on large volumes; use --depth N to go deeper.
DEFAULT_SCAN_DEPTH = 5

# Directories pruned from every find scan.
_PRUNE_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
_PRUNE_EXPR = " -o ".join(f"-name {d}" for d in sorted(_PRUNE_DIRS))


def _workdir_relative(containerpath: str, workdir: str) -> str:
    """Convert an absolute container path to a workdir-relative path."""
    workdir = workdir.rstrip("/")
    containerpath = containerpath.rstrip("/")
    if containerpath.startswith(workdir + "/"):
        return containerpath[len(workdir) + 1 :]
    if containerpath == workdir:
        return "."
    return containerpath


def _resolve_to_host(relative_path: str, config: DockerConfig) -> tuple[str, str] | None:
    """Map a workdir-relative path to the host path where it lives.

    Checks data volumes first (most specific match wins), then falls back to
    the code mount (project root → containerworkdir).
    """
    workdir = config.containerworkdir.rstrip("/")
    for volume in (config.volumes or []):
        containerpath = volume["containerpath"].rstrip("/")
        hostpath = volume["hostpath"].rstrip("/")
        vol_relative = _workdir_relative(containerpath, workdir)
        if vol_relative == ".":
            # Volume is mounted at workdir itself — matches any relative path.
            return hostpath + "/" + relative_path, hostpath
        if relative_path.startswith(vol_relative + "/") or relative_path == vol_relative:
            suffix = relative_path[len(vol_relative) :]
            return hostpath + suffix, hostpath
    # Fall back to the code mount (project root → containerworkdir).
    if cli_config.remote_path:
        return cli_config.remote_path.rstrip("/") + "/" + relative_path, cli_config.remote_path
    return None


def _build_tree(paths: list[str], strip_prefix: str) -> dict:
    """Convert a flat list of absolute paths into a nested dict.

    Each key is a path component; files map to an empty dict,
    directories to a non-empty dict of their children.
    """
    root: dict = {}
    prefix = strip_prefix.rstrip("/")
    for path in paths:
        path = path.strip()
        if not path:
            continue
        if path.startswith(prefix + "/"):
            relative = path[len(prefix) + 1 :]
        elif path == prefix:
            continue
        else:
            relative = path
        node = root
        for part in relative.split("/"):
            if part:
                node = node.setdefault(part, {})
    return root


def _dict_to_rich_tree(d: dict, tree: Tree, remaining_depth: int | None = None) -> None:
    """Recursively populate a rich Tree from a nested dict.

    Directories (non-empty children) are listed before files, sorted alphabetically.
    remaining_depth: how many more directory levels to expand fully; None = unlimited.
    Directories at the limit are shown with a '...' child to signal truncated content.
    """
    dirs = {k: v for k, v in d.items() if v}
    files = {k: v for k, v in d.items() if not v}
    for name in sorted(dirs):
        branch = tree.add(f"[bold blue]{name}/[/bold blue]")
        if remaining_depth is None:
            _dict_to_rich_tree(dirs[name], branch, None)
        elif remaining_depth > 1:
            _dict_to_rich_tree(dirs[name], branch, remaining_depth - 1)
        else:
            branch.add("[dim]...[/dim]")
    for name in sorted(files):
        tree.add(name)


def execute_volumes(
    config: DockerConfig,
    depth: int | None = None,
    imagename: str | None = None,
    volumes: list | None = None,
) -> None:
    """List volume files as they appear inside the container, rooted at containerworkdir."""
    volumes = volumes if volumes is not None else (config.volumes or [])
    workdir = (config.containerworkdir or "/").rstrip("/") or "/"

    # Build the full list of mounts: code mount first, then data volumes.
    # The code mount maps the local project root to containerworkdir, exactly as submit does.
    mounts: list[dict] = []
    if cli_config.remote_path:
        mounts.append({"hostpath": cli_config.remote_path, "containerpath": workdir})
    mounts.extend(volumes)

    # Scan depth for find: depth+1 ensures folder nodes at the display limit are non-empty.
    # Without --depth, use DEFAULT_SCAN_DEPTH to keep find fast on large volumes.
    scan_depth = depth + 1 if depth is not None else DEFAULT_SCAN_DEPTH

    container_paths: list[str] = []

    with get_client() as client:
        for mount in mounts:
            hostpath = mount["hostpath"].rstrip("/")
            containerpath = mount["containerpath"].rstrip("/")

            cmd = f"find {hostpath} -maxdepth {scan_depth} \\( {_PRUNE_EXPR} \\) -prune -o -type f -print 2>/dev/null"
            exit_code, stdout = client.run(cmd, cwd=None, capture=True)

            if exit_code != 0 or not stdout.strip():
                continue

            for line in stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith(hostpath + "/"):
                    container_paths.append(containerpath + "/" + line[len(hostpath) + 1 :])
                elif line != hostpath:
                    container_paths.append(containerpath + "/" + line)

    tree = Tree(f"[bold]{workdir}[/bold]")
    if not container_paths:
        tree.add("[dim](empty or inaccessible)[/dim]")
    else:
        _dict_to_rich_tree(_build_tree(container_paths, workdir), tree, remaining_depth=depth)

    Console().print(tree)
