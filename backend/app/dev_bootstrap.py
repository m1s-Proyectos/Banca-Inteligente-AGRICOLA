from app.db.base import Base
from app.db.session import engine
from app.models import entities  # noqa: F401
from app.seed import main as seed_main


def main() -> None:
    Base.metadata.create_all(bind=engine)
    seed_main()


if __name__ == "__main__":
    main()

