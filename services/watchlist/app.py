"""Start the app with: python app.py"""

import logging
import sys
from pathlib import Path

from waitress import serve

from app import create_app
from app.config import RedactSecret, load_config, load_env_file
from app.poller import start_poller

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

# Optional: a git-ignored .env next to this file. Real environment variables win.
load_env_file(Path(__file__).parent / ".env")
config = load_config()
# Belt and braces: even a library log line can never print the Finnhub key.
for handler in logging.getLogger().handlers:
    handler.addFilter(RedactSecret(config.price_api_key))
# The stream logs its own short warnings, so the library's verbose ones are muted.
logging.getLogger("websocket").setLevel(logging.CRITICAL)
logging.info("Starting on %s:%s with database %s", config.host, config.port, config.db_path)
app = create_app(config)
app.extensions["price_stream"].start()
start_poller(app.extensions["alert_service"], config.poll_interval_seconds)
serve(app, host=config.host, port=config.port)
