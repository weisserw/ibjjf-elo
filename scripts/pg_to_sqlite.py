#!/usr/bin/env python3
import argparse
import os
import sys
from typing import Iterable, List, Type

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
)

from extensions import db  # noqa: E402
import models  # noqa: E402


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
