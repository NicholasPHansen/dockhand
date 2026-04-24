"""Docker volume inspection and path resolution."""

from rich.console import Console
from rich.tree import Tree

from dockhand.client import get_client
from dockhand.config import DockerConfig


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
    """Map a workdir-relative path back to a host path and volume hostpath."""
    workdir = config.containerworkdir.rstrip("/")
    for volume in config.volumes:
        containerpath = volume["containerpath"].rstrip("/")
        hostpath = volume["hostpath"].rstrip("/")
        vol_relative = _workdir_relative(containerpath, workdir)
        if relative_path.startswith(vol_relative + "/") or relative_path == vol_relative:
            suffix = relative_path[len(vol_relative) :]
            return hostpath + suffix, hostpath
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
            node = node.setdefault(part, {})
    return root


def _dict_to_rich_tree(d: dict, tree: Tree) -> None:
    """Recursively populate a rich Tree from a nested dict.

    Directories (non-empty children) are listed before files, sorted alphabetically.
    """
    dirs = {k: v for k, v in d.items() if v}
    files = {k: v for k, v in d.items() if not v}
    for name in sorted(dirs):
        branch = tree.add(f"[bold blue]{name}/[/bold blue]")
        _dict_to_rich_tree(dirs[name], branch)
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

    maxdepth = f"-maxdepth {depth} " if depth is not None else ""

    container_paths: list[str] = []

    with get_client() as client:
        for volume in volumes:
            hostpath = volume["hostpath"].rstrip("/")
            containerpath = volume["containerpath"].rstrip("/")

            command = f"find {hostpath} {maxdepth}-type f 2>/dev/null"
            exit_code, stdout = client.run(command, cwd=None, capture=True)

            if exit_code != 0 or not stdout.strip():
                continue

            for line in stdout.strip().splitlines():
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
        _dict_to_rich_tree(_build_tree(container_paths, workdir), tree)

    Console().print(tree)
