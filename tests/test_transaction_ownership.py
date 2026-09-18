import ast
from pathlib import Path


REPOSITORIES = Path("app/modules").glob("*/repository.py")


def test_repositories_never_commit_or_rollback_transactions():
    violations = []
    for path in REPOSITORIES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Await) or not isinstance(node.value, ast.Call):
                continue
            function = node.value.func
            if isinstance(function, ast.Attribute) and function.attr in {"commit", "rollback"}:
                violations.append(f"{path}:{node.lineno} calls {function.attr}()")
    assert violations == [], "Transaction ownership violations:\n" + "\n".join(violations)


class FakeSession:
    def __init__(self):
        self.flushed = False
        self.added = []

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flushed = True

    async def commit(self):
        raise AssertionError("repository must not commit")

    async def rollback(self):
        raise AssertionError("repository must not rollback")
