import subprocess

from dockhand.client.base import Client
from dockhand.client.local import LocalClient
from dockhand.client.ssh import SSHClient


def get_client() -> Client:
    # We assume that only HPC has access to the bstat command and use this to determine if we are on the HPC.
    try:
        subprocess.check_output("bstat", shell=True, stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return LocalClient()
    except subprocess.CalledProcessError:
        return SSHClient()
