"""Start the app with: python app.py"""

import logging
import sys

from waitress import serve

from app import create_app
from app.config import load_config

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

config = load_config()
logging.info("Starting on %s:%s with database %s", config.host, config.port, config.db_path)
serve(create_app(config), host=config.host, port=config.port)
