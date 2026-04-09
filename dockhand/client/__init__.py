import socket
import subprocess

from dockhand.client.base import Client
from dockhand.client.local import LocalClient
from dockhand.client.ssh import SSHClient
from dockhand.config import cli_config


def _is_localhost(hostname: str) -> bool:
    """Check if hostname is localhost or resolves to 127.0.0.1/::1."""
    if hostname in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        # Resolve hostname to IP and check if it's loopback
        ip = socket.gethostbyname(hostname)
        return ip.startswith("127.")
    except (socket.gaierror, socket.error):
        # If resolution fails, assume it's not localhost
        return False


def get_client() -> Client:
    # Check if hostname is localhost or not set - use local client
    if cli_config.ssh is None or _is_localhost(cli_config.ssh.hostname):
        return LocalClient()
    # Otherwise try bstat to detect if we're already on the remote machine
    try:
        subprocess.check_output("bstat", shell=True, stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return LocalClient()
    except subprocess.CalledProcessError:
        return SSHClient()
