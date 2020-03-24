import yaml


class ConfigError(KeyError):
    pass


class ConfigHandler:
    MANDATORY_FIELDS = ["flows", "controller_baseurl", "ovsdb_addr"]

    def __init__(self, config_path: str):
        """
        Create a configuration handler and run basic validations.

        Raises relevant errors when file is not found, or YAML is incorrect.

        :param config_path: Path to the configuration file.
        :raises ConfigError: When mandatory fields are not present in the file.
        """
        self.config_path = config_path
        with open(self.config_path, "r") as f:
            self.config = yaml.load(f, Loader=yaml.Loader)

        # Check for mandatory fields
        missing = []
        for field in ConfigHandler.MANDATORY_FIELDS:
            try:
                if field not in self.config:
                    missing.append(field)
            except TypeError:
                # On *empty* config files, yaml loads a None type object which is not iterable, so the `in` operation
                # will raise a TypeError
                missing = self.__class__.MANDATORY_FIELDS
                break
        if len(missing) > 0:
            raise ConfigError("The following keys are missing from the config: {}".format(missing))
