import yaml


class ConfigError(KeyError):
    pass


class ConfigHandler:
    MANDATORY_FIELDS = ["flows", "ovsdb_addr"]

    def __init__(self, config_path: str):
        """
        Create a configuration handler and run basic validations.

        Raises relevant errors when files are not found, or YAML is incorrect.
        Raises `ConfigError` when mandatory fields are not present in the file.

        :param config_path: Path to the configuration file
        """
        self.config_path = config_path
        with open(self.config_path, "r") as f:
            self.config = yaml.load(f, Loader=yaml.Loader)

        # Check for mandatory fields
        missing = []
        for field in ConfigHandler.MANDATORY_FIELDS:
            if field not in self.config:
                missing.append(field)
        if len(missing) > 0:
            raise ConfigError("The following keys are missing from the config: {}".format(missing))
