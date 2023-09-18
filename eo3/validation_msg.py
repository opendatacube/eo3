import enum
from typing import Generator, Mapping, Optional

from attr import frozen


class Level(enum.Enum):
    info = 1
    warning = 2
    error = 3


@frozen
class ValidationMessage:
    level: Level
    code: str
    reason: str
    hint: Optional[str] = None
    #: What was assumed when validating this? Eg: dict(product='ls7_nbar', metadata_type='eo3')
    context: Optional[Mapping] = None

    def __str__(self) -> str:
        hint = ""
        if self.hint:
            hint = f" (Hint: {self.hint})"
        if self.context:
            context_str = ",".join(f"{k}: {v}" for k, v in self.context.items())
            return f"{self.code} in [{context_str}]: {self.reason}{hint}"
        else:
            return f"{self.code}: {self.reason}{hint}"

    @classmethod
    def info(
        cls, code: str, reason: str, hint: str = None, context: Optional[Mapping] = None
    ) -> "ValidationMessage":
        return ValidationMessage(Level.info, code, reason, hint=hint, context=context)

    @classmethod
    def warning(
        cls, code: str, reason: str, hint: str = None, context: Optional[Mapping] = None
    ) -> "ValidationMessage":
        return ValidationMessage(
            Level.warning, code, reason, hint=hint, context=context
        )

    @classmethod
    def error(
        cls, code: str, reason: str, hint: str = None, context: Optional[Mapping] = None
    ) -> "ValidationMessage":
        return ValidationMessage(Level.error, code, reason, hint=hint, context=context)


ValidationMessages = Generator[ValidationMessage, None, None]


class ContextualMessager:
    def __init__(self, context: dict):
        self.context = context
        self.errors = 0

    def info(self, code: str, reason: str, hint: str = None):
        return ValidationMessage.info(code, reason, hint=hint, context=self.context)

    def warning(self, code: str, reason: str, hint: str = None):
        return ValidationMessage.warning(code, reason, hint=hint, context=self.context)

    def error(self, code: str, reason: str, hint: str = None):
        self.errors += 1
        return ValidationMessage.error(code, reason, hint=hint, context=self.context)

    def sub_msg(self, **kwargs: str) -> "ContextualMessager":
        sub_context = self.context.copy()
        sub_context.update(**kwargs)
        return self.__class__(sub_context)
