import fabric

from dockhand.client.base import Client
from dockhand.config import cli_config
from dockhand.constants import CONFIG_FILENAME


class SSHClient(Client):
    def __init__(self, hostname: str | None = None):
        super().__init__()

        cli_config.check_ssh(msg=f"Please provide a SSH configuration in '{CONFIG_FILENAME}'.")

        self.client = fabric.Connection(
            host=hostname or cli_config.ssh.hostname,
            user=cli_config.ssh.user,
            connect_kwargs={"key_filename": cli_config.ssh.identityfile},
        )

    def close(self):
        self.client.close()

    def run(self, command: str, cwd: str | None = None, capture: bool = False) -> tuple[int, str]:
        command = f'bash -l -c "{command}"'
        hide = "both" if capture else None
        if cwd is not None:
            with self.client.cd(cwd):
                result = self.client.run(command, warn=True, hide=hide)
        else:
            result = self.client.run(command, warn=True, hide=hide)
        return result.exited, result.stdout

    def remove(self, path: str):
        sftp = self.client.sftp()
        sftp.remove(path)

    def exists(self, path):
        sftp = self.client.sftp()
        try:
            sftp.stat(path)
            return True
        except FileNotFoundError:
            return False

    def load(self, path: str) -> str:
        sftp = self.client.sftp()
        with sftp.file(path, "r") as f:
            return f.read().decode("utf-8")

    def save(self, path: str, contents: str):
        sftp = self.client.sftp()
        with sftp.file(path, "w") as f:
            f.write(contents)
