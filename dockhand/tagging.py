"""Image tag resolution for baked code delivery."""
import hashlib
import time

from git import Repo

from dockhand.config import cli_config


def resolve_image_ref(imagename: str, unique: bool) -> str:
    """Return the image ref to build and run for baked code delivery.

    ``unique=True`` (queued jobs) produces an immutable, content-addressed tag so a
    job waiting in the queue is pinned to the exact code it was submitted with, and
    a later submit cannot retroactively change it. ``unique=False`` (immediate,
    unqueued run) reuses a single tag since there is no drift window to guard against.
    """
    if not unique:
        return imagename  # implicit :latest, rebuilt on each submit
    return f"{imagename}:{_content_tag()}"


def _content_tag() -> str:
    """Derive a tag from the project's git state.

    A clean worktree maps to its commit sha (fully reproducible). A dirty worktree
    folds tracked changes and untracked filenames into the tag so distinct working
    states get distinct images while identical states dedupe. Note that untracked
    file *contents* are not hashed — commit before queued submits for a guaranteed
    immutable snapshot. Falls back to a time-based tag outside a git repo.
    """
    try:
        repo = Repo(cli_config.project_root)
        sha = repo.head.commit.hexsha[:12]
        dirty = repo.is_dirty(untracked_files=True)
        diff = repo.git.diff() if dirty else ""
        untracked = sorted(repo.untracked_files) if dirty else []
    except Exception:
        return f"ts-{int(time.time())}"

    if not dirty:
        return sha

    h = hashlib.sha256()
    h.update(diff.encode())
    for path in untracked:
        h.update(path.encode())
    return f"{sha}-dirty-{h.hexdigest()[:8]}"
