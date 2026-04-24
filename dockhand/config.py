import dataclasses
import json
from hashlib import sha256
from pathlib import Path
from typing import List

from dockhand.constants import CONFIG_FILENAME, HISTORY_FILENAME
from dockhand.error import error_and_exit


@dataclasses.dataclass
class DockerVolumesConfig:
    hostpath: str
    containerpath: str
    permissions: str


@dataclasses.dataclass
class DockerResubmitConfig:
    container_id: str | None
    commands: List[str] | None
    dockerfile: str | None
    imagename: str | None
    gpus: str | None


@dataclasses.dataclass
class DockerConfig:
    dockerfile: str
    imagename: str
    volumes: list[DockerVolumesConfig]
    ports: list[str]
    gpus: str
    containerworkdir: str
    slots: int = 1

    @classmethod
    def load(cls, config: dict):
        if "docker" not in config:
            return None

        docker = config["docker"]
        if "dockerfile" not in docker:
            error_and_exit('"dockerfile" not found in docker config.')

        if "volumes" not in docker:
            error_and_exit('"volumes" not found in docker config.')

        if "imagename" not in docker:
            error_and_exit('"imagename" not found in docker config.')

        if "gpus" not in docker:
            docker["gpus"] = None

        if "ports" not in docker:
            docker["ports"] = None

        if "containerworkdir" not in docker:
            docker["containerworkdir"] = "/"

        if "slots" not in docker:
            docker["slots"] = 1

        # Only pass fields that DockerConfig expects
        return cls(
            dockerfile=docker["dockerfile"],
            imagename=docker["imagename"],
            volumes=docker["volumes"],
            ports=docker["ports"],
            gpus=docker["gpus"],
            containerworkdir=docker["containerworkdir"],
            slots=docker["slots"],
        )

    @classmethod
    def validate(cls, config: dict) -> dict:
        if not isinstance(config, dict):
            error_and_exit(f"Invalid type for ssh option in config. Expected dictionary but got {type(config)}.")

        output = {}

        dockerfile = config.get("dockerfile")
        if dockerfile is not None:
            if not isinstance(dockerfile, str):
                error_and_exit(f"Invalid type for dockerfile. Expected string, got {type(dockerfile).__name__}.")
            output["dockerfile"] = dockerfile

        imagename = config.get("imagename")
        if imagename is not None:
            if not isinstance(imagename, str):
                error_and_exit(
                    f"Invalid type for compose_file option in docker config. Expected string but got {type(imagename)}."
                )
            output["imagename"] = imagename

        volumes = config.get("volumes")
        if volumes is not None:
            if not isinstance(volumes, str):
                error_and_exit(
                    f"Invalid type for compose_file option in docker config. Expected string but got {type(volumes)}."
                )
            output["volumes"] = volumes

        ports = config.get("ports")
        if ports is not None:
            if not isinstance(ports, str):
                error_and_exit(
                    f"Invalid type for compose_file option in docker config. Expected string but got {type(ports)}."
                )
            output["ports"] = ports

        gpus = config.get("gpus")
        if gpus is not None:
            if not isinstance(gpus, str):
                error_and_exit(
                    f"Invalid type for gpus option in docker config. Expected string but got {type(gpus).__name__}."
                )
            output["gpus"] = gpus

        slots = config.get("slots")
        if slots is not None:
            if not isinstance(slots, int) or slots < 1:
                error_and_exit(
                    f"Invalid value for slots option in docker config. Expected a positive integer but got {slots!r}."
                )
            output["slots"] = slots

        return output


@dataclasses.dataclass
class QueueConfig:
    enabled: bool = False
    tool: str = "task_spooler"

    @classmethod
    def load(cls, config: dict):
        if "queue" not in config:
            return cls()
        queue = config["queue"]
        if not isinstance(queue, dict):
            error_and_exit(f"Invalid type for queue option in config. Expected dictionary but got {type(queue)}.")
        enabled = queue.get("enabled", False)
        tool = queue.get("tool", "task_spooler")
        return cls(enabled=enabled, tool=tool)


@dataclasses.dataclass
class SSHConfig:
    hostname: str
    user: str
    identityfile: str

    @classmethod
    def load(cls, config: dict):
        if "ssh" not in config:
            return None

        ssh = config["ssh"]
        ssh = SSHConfig.validate(ssh)

        if "hostname" not in ssh:
            error_and_exit('"hostname" not found in SSH config.')

        if "user" not in ssh:
            error_and_exit('"user" not found in SSH config.')

        if "identityfile" not in ssh:
            error_and_exit('"identityfile" not found in SSH config')

        return cls(**ssh)

    @classmethod
    def validate(cls, config: dict) -> dict:
        if not isinstance(config, dict):
            error_and_exit(f"Invalid type for ssh option in config. Expected dictionary but got {type(config)}.")

        output = {}

        hostname = config.get("hostname")
        if hostname is not None:
            if not isinstance(hostname, str):
                error_and_exit(f"Invalid type for host option in ssh config. Expected string but got {type(hostname)}.")
            output["hostname"] = hostname

        user = config.get("user")
        if user is not None:
            if not isinstance(user, str):
                error_and_exit(f"Invalid type for user option in ssh config. Expected string but got {type(user)}.")
            output["user"] = user

        identityfile = config.get("identityfile")
        if identityfile is not None:
            if not isinstance(identityfile, str):
                error_and_exit(
                    f"Invalid type for identityfile option in ssh config. Expected string but got {type(identityfile)}."
                )
            output["identityfile"] = str(Path(identityfile).expanduser())

        return output


@dataclasses.dataclass
class CLIConfig:
    history_path: Path
    project_root: Path
    remote_path: str
    sync: bool
    profiles: dict | None
    ssh: SSHConfig | None
    docker: DockerConfig | None
    queue: QueueConfig = dataclasses.field(default_factory=QueueConfig)

    @classmethod
    def load(cls):
        project_root = cls.get_project_root()

        git_path = project_root / ".git"
        if not git_path.exists():
            error_and_exit(f"Could not find git repository at '{git_path}'.")

        path = project_root / CONFIG_FILENAME

        try:
            config = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            error_and_exit(f"Error while parsing config file at '{path}':\n{e}")

        if not isinstance(config, dict):
            error_and_exit(f"Invalid type for config. Expected dictionary but got {type(config)}.")

        profiles = config.get("profiles")
        if profiles is not None and not isinstance(profiles, dict):
            error_and_exit(f"Invalid type for profiles option in config. Expected dictionary but got {type(profiles)}.")

        history_path = cls.load_history_path(config, project_root)
        remote_path = cls.load_remote_path(config, project_root)
        sync = config.get("sync", True)
        ssh = SSHConfig.load(config)
        docker = DockerConfig.load(config)
        queue = QueueConfig.load(config)

        return cls(
            history_path=history_path,
            profiles=profiles,
            project_root=project_root,
            remote_path=remote_path,
            sync=sync,
            ssh=ssh,
            docker=docker,
            queue=queue,
        )

    @classmethod
    def get_project_root(cls) -> Path:
        """Assume that config file exist in the project root and use that to get the project root."""
        root = Path("/")
        current_path = Path.cwd()
        while current_path != root:
            if (current_path / CONFIG_FILENAME).exists():
                return current_path
            current_path = current_path.parent

        if (root / CONFIG_FILENAME).exists():
            return root

        error_and_exit(
            f"Could not find project root. Make sure that '{CONFIG_FILENAME}' exists in the root of the project."
        )

    @classmethod
    def load_history_path(cls, config: dict, project_root: Path) -> Path:
        if "history_path" in config:
            history_path = config["history_path"]
            if not isinstance(history_path, str):
                error_and_exit(
                    f"Invalid type for history_path option in config. Expected string but got {type(history_path)}."
                )
            return Path(history_path)
        return project_root / HISTORY_FILENAME

    @classmethod
    def load_remote_path(cls, config: dict, project_root: Path) -> str:
        if "remote_path" in config:
            return config["remote_path"]

        name = project_root.name
        hash = sha256(str(project_root).encode()).hexdigest()[:8]
        return f"~/{name}-{hash}"

    def check_ssh(self, msg: str = "SSH configuration is required for this command."):
        if self.ssh is None:
            error_and_exit(msg)

    def check_docker(self, msg: str = "Docker configuration is required for this command"):
        if self.docker is None:
            error_and_exit(msg)

    def load_profile(self, name: str):
        if name not in self.profiles:
            error_and_exit(f"Profile '{name}' not found in config.")

        profile = self.profiles[name]

        if "history_path" in profile:
            self.history_path = CLIConfig.load_history_path(profile, self.project_root)

        if "remote_path" in profile:
            self.remote_path = profile["remote_path"]

        if "ssh" in profile:
            ssh = SSHConfig.validate(profile["ssh"])
            self.ssh = dataclasses.replace(self.ssh, **ssh)


cli_config = CLIConfig.load()
