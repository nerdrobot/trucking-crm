"""Small parameterized SQL boundary shared by D1 and local SQLite."""

from typing import Protocol


class Database(Protocol):
    async def first(self, sql: str, *values): ...
    async def all(self, sql: str, *values): ...
    async def run(self, sql: str, *values): ...
    async def batch(self, statements: list[tuple]): ...


def native(value):
    return value.to_py() if hasattr(value, "to_py") else value


class D1Database:
    def __init__(self, binding):
        self.binding = binding

    async def first(self, sql, *values):
        row = await self.binding.prepare(sql).bind(*values).first()
        return dict(native(row)) if row is not None else None

    async def all(self, sql, *values):
        result = native(await self.binding.prepare(sql).bind(*values).all())
        return [dict(native(row)) for row in result["results"]]

    async def run(self, sql, *values):
        result = native(await self.binding.prepare(sql).bind(*values).run())
        return result["meta"]["changes"]

    async def batch(self, statements):
        return await self.binding.batch(
            [self.binding.prepare(sql).bind(*values) for sql, *values in statements]
        )
