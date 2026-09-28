"""Entry point: `python app.py` is the single documented start command."""

import logging
import sys

from waitress import serve

from pricewatch import create_app
from pricewatch.config import Config


def main() -> None:
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = Config.from_env()
    app = create_app(config)
    logging.getLogger("pricewatch").info(
        "Serving on %s:%s, database at %s", config.host, config.port, config.db_path
    )
    serve(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
