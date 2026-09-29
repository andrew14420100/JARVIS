from enum import Enum


class SecurityLevel(str, Enum):
    SAFE = "safe"
    CONFIRMATION_REQUIRED = "confirmation_required"
    BLOCKED = "blocked"


class ToolBlockedError(PermissionError):
    pass


class ConfirmationRequiredError(PermissionError):
    def __init__(self, tool_name: str, message: str):
        super().__init__(message)
        self.tool_name = tool_name
        self.message = message
