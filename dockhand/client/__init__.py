import subprocess

from dockhand.client.base import Client
from dockhand.client.local import LocalClient
from dockhand.client.ssh import SSHClient
from dockhand.config import cli_config


def get_client() -> Client:
    # Check if hostname is localhost or not set - use local client
    if cli_config.ssh is None or cli_config.ssh.hostname in ("localhost", "127.0.0.1"):
        return LocalClient()
    # Otherwise try bstat to detect if we're already on the remote machine
    try:
        subprocess.check_output("bstat", shell=True, stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return LocalClient()
    except subprocess.CalledProcessError:
        return SSHClient()
