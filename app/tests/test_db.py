import importlib
import os
import shutil
import sys
import tempfile

from sqlalchemy import create_engine

from extensions import db


def setup_test_app():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")
    if "app" in sys.modules:
        del sys.modules["app"]
    app_module = importlib.import_module("app")
    app_module.app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    with app_module.app.app_context():
        sqlalchemy_ext = app_module.app.extensions.get("sqlalchemy")
        if sqlalchemy_ext and getattr(sqlalchemy_ext, "engines", None) is not None:
            sqlalchemy_ext.engines[None] = create_engine(f"sqlite:///{db_path}")
    return app_module, temp_dir


def teardown_test_app(app_module, temp_dir):
    with app_module.app.app_context():
        sqlalchemy_ext = app_module.app.extensions.get("sqlalchemy")
        if sqlalchemy_ext and getattr(sqlalchemy_ext, "engines", None):
            engine = sqlalchemy_ext.engines.get(None)
            if engine:
                engine.dispose()
        db.session.remove()
        db.drop_all()
    shutil.rmtree(temp_dir)


class TestDbMixin:
    app_module = None
    temp_dir = None

    @classmethod
    def setUpClass(cls):
        cls.app_module, cls.temp_dir = setup_test_app()
        with cls.app_module.app.app_context():
            db.drop_all()
            db.create_all()
            cls._seed_data()

    @classmethod
    def tearDownClass(cls):
        teardown_test_app(cls.app_module, cls.temp_dir)
