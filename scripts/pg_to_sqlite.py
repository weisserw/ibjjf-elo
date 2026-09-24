#!/usr/bin/env python3
"""Copy a PostgreSQL application database to a fresh SQLite file.

The script creates its own schema. Do not run Flask migrations on the target:
SQLite treats bare UUID columns as numeric, which can collapse distinct UUIDs
into the same numeric value. Use a new destination path for every attempt.
"""
import argparse
import os
import sys
from typing import Iterable, List, Type

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
)

from extensions import db  # noqa: E402
import models  # noqa: E402


@compiles(UUID, "sqlite")
def compile_uuid_as_text(_type, _compiler, **_kwargs):
    """SQLite's bare UUID declaration has NUMERIC affinity and corrupts hex IDs."""
    return "TEXT"


def prepare_destination(engine):
    """Create a fresh SQLite schema with text-backed UUIDs, never reuse a partial copy."""
    existing = inspect(engine).get_table_names()
    if existing:
        raise ValueError(
            "Destination already has tables; use a new SQLite path for a fresh copy"
        )
    db.metadata.create_all(engine)
    with engine.connect() as connection:
        uuid_columns = connection.execute(
            text("PRAGMA table_info(result_medals)")
        ).all()
    id_type = next(row[2] for row in uuid_columns if row[1] == "id")
    if id_type.upper() != "TEXT":
        raise RuntimeError(f"result_medals.id must be TEXT in SQLite, got {id_type}")


def iter_models() -> List[Type[db.Model]]:
    model_classes = []
    for obj in models.__dict__.values():
        if isinstance(obj, type) and issubclass(obj, db.Model):
            if getattr(obj, "__tablename__", None) is None:
                continue
            model_classes.append(obj)
    model_classes.sort(key=lambda cls: cls.__tablename__)
    return model_classes


def chunked(iterable: Iterable, size: int):
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def model_to_mapping(obj, model_cls):
    return {col.key: getattr(obj, col.key) for col in model_cls.__table__.columns}


def copy_table(model_cls, src_session, dst_session, batch_size: int):
    query = src_session.query(model_cls).yield_per(batch_size)
    total = 0
    for batch in chunked(query, batch_size):
        mappings = [model_to_mapping(row, model_cls) for row in batch]
        dst_session.bulk_insert_mappings(model_cls, mappings)
        dst_session.commit()
        total += len(mappings)
    return total


def main():
    parser = argparse.ArgumentParser(
        description="Copy data from Postgres to a sqlite database using app/models.py",
    )
    parser.add_argument("--pg-url", required=True, help="Postgres connection string")
    parser.add_argument("--sqlite-path", required=True, help="Target sqlite db file")
    parser.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args()

    pg_engine = create_engine(args.pg_url)
    sqlite_engine = create_engine(f"sqlite:///{args.sqlite_path}")
    prepare_destination(sqlite_engine)

    SrcSession = sessionmaker(bind=pg_engine)
    DstSession = sessionmaker(bind=sqlite_engine)

    src_session = SrcSession()
    dst_session = DstSession()

    try:
        dst_session.execute(text("PRAGMA foreign_keys=OFF"))
        dst_session.commit()

        model_classes = iter_models()
        for model_cls in model_classes:
            count = copy_table(model_cls, src_session, dst_session, args.batch_size)
            print(f"{model_cls.__tablename__}: {count}")
    finally:
        src_session.close()
        dst_session.close()


if __name__ == "__main__":
    main()
