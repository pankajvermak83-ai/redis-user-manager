class UserManagerError(Exception):
    pass


class UserAlreadyExistsException(UserManagerError):
    pass


class UserNotFoundException(UserManagerError):
    pass


class MissingEnvironmentVariableException(UserManagerError):
    pass
