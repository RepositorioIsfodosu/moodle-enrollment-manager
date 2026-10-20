from alembic import context
from app.db.session import get_engine
from app.models import Base


def offline():
    raise RuntimeError("Use online migrations; database credentials must not enter SQL output")


def online():
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    offline()
else:
    online()
