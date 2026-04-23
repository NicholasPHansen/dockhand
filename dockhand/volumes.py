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


def _find_files(client, hostpath: str, depth: int | None) -> tuple[int, str]:
    """Run find via the client to list files under hostpath."""
    maxdepth = f"-maxdepth {depth} " if depth is not None else ""
    return client.run(f"find {hostpath} {maxdepth}-type f 2>/dev/null", cwd=None)


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


def execute_volumes(config: DockerConfig, depth: int | None = None) -> None:
    """List files in docker-mounted volumes as a tree."""
    if not config.volumes:
        Console().print("No volumes configured.")
        return

    console = Console()

    with get_client() as client:
        for volume in config.volumes:
            hostpath = volume["hostpath"].rstrip("/")
            vol_relative = _workdir_relative(volume["containerpath"], config.containerworkdir)

            exit_code, stdout = _find_files(client, hostpath, depth)

            tree = Tree(f"[bold]{vol_relative}/[/bold]")

            if exit_code != 0 or not stdout.strip():
                tree.add("[dim](empty or inaccessible)[/dim]")
            else:
                lines = [line for line in stdout.strip().splitlines() if line.strip()]
                _dict_to_rich_tree(_build_tree(lines, hostpath), tree)

            console.print(tree)
