"""Decode an explicit set of historical enum values without enabling new writes."""
from sqlalchemy import Enum as SAEnum
from sqlalchemy.types import TypeDecorator


class LegacyEnumValue(str):
    @property
    def value(self):
        return str(self)


class LegacyReadableEnum(TypeDecorator):
    """Keep current DDL / public enums while allowing known stored legacy values.

    The underlying native enum still describes only current values. Legacy
    databases retain their wider enum through the exact legacy schema profile.
    Unknown stored values raise LookupError rather than silently turning into
    a current state or metric. Application writes continue using current enums.
    """

    impl = SAEnum
    cache_ok = True

    def __init__(self, enum_class, *, legacy_values=()):
        self.enum_class = enum_class
        self.legacy_values = tuple(legacy_values)
        super().__init__(enum_class, values_callable=lambda values: [entry.value for entry in values])

    def result_processor(self, dialect, coltype):
        # Bypass SAEnum's current-only decoder for reads, not its bind/DDL type.
        def process(value):
            if value is None:
                return None
            try:
                return self.enum_class(value)
            except ValueError as exc:
                if value in self.legacy_values:
                    return LegacyEnumValue(value)
                raise LookupError("Unrecognized stored enum value") from exc

        return process
