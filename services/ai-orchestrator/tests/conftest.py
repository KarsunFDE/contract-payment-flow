"""
tests/conftest.py — shared unit-test fixtures.

The suite runs with NO MongoDB (mirrors test_day0_scaffolding.py). The
implemented workflow nodes now write audit/idempotency records through
db.get_db(), so an autouse fixture swaps in a minimal in-memory fake: the
fail-closed writers exercise their REAL logic (insert, find, upsert) without a
server. Aggregation pipelines raise OperationFailure — mirroring a server with
no Atlas $vectorSearch/$search index — so the retrieval read path exercises its
degraded/fail-soft branches instead of hanging on server selection.

Set RUN_WITH_REAL_MONGO=1 to disable the fake (container/integration runs).
"""
from __future__ import annotations

import os

import pytest
from pymongo.errors import OperationFailure

from app import db
from app.workflow import retrieve_client


def _matches(doc: dict, query: dict) -> bool:
    """Top-level equality matching — all the workflow writers need."""
    return all(doc.get(k) == v for k, v in query.items())


class FakeCollection:
    def __init__(self, name: str):
        self.name = name
        self.docs: list[dict] = []

    def insert_one(self, doc: dict):
        self.docs.append(dict(doc))

    def update_one(self, query: dict, update: dict, upsert: bool = False):
        for doc in self.docs:
            if _matches(doc, query):
                doc.update(update.get("$set", {}))
                return
        if upsert:
            merged = dict(query)
            merged.update(update.get("$set", {}))
            self.docs.append(merged)

    def find_one(self, query: dict | None = None):
        for doc in self.docs:
            if _matches(doc, query or {}):
                return doc
        return None

    def find(self, query: dict | None = None):
        return [doc for doc in self.docs if _matches(doc, query or {})]

    def count_documents(self, query: dict | None = None) -> int:
        return len(self.find(query))

    def create_index(self, *args, **kwargs):
        return "fake_index"

    def aggregate(self, *args, **kwargs):
        # No Atlas search indexes in unit tests — same failure shape a bare
        # mongod gives, which the retrieval router handles as a degraded path.
        raise OperationFailure("no $vectorSearch/$search in unit-test fake")


class FakeDb:
    def __init__(self):
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self.collections:
            self.collections[name] = FakeCollection(name)
        return self.collections[name]


@pytest.fixture(autouse=True)
def fake_mongo(monkeypatch):
    """In-memory Mongo stand-in for every test (opt out: RUN_WITH_REAL_MONGO=1)."""
    if os.environ.get("RUN_WITH_REAL_MONGO"):
        yield None
        return
    fake = FakeDb()
    monkeypatch.setattr(db, "get_db", lambda: fake)
    yield fake


@pytest.fixture(autouse=True)
def _restore_retrieve_client():
    """Tests swap the workflow's retrieve client via set_client(); restore the
    real implementation after EVERY test so a setup failure between a swap and
    its try/finally can never leak a fake into later tests."""
    yield
    retrieve_client.set_client(retrieve_client.RouterRetrieveClient())
