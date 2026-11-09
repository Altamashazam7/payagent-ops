"""Shared JSON-compatible values used by persisted audit metadata."""

type JSONValue = (
    str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]
)
