"""Start the watchlist service with: python app.py"""

import logging
import sys
from pathlib import Path

from waitress import serve

from app import create_app
from app.config import RedactSecret, load_config, load_env_file

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

# Optional: a git-ignored .env next to this file. Real environment variables win.
load_env_file(Path(__file__).parent / ".env")
config = load_config()
# Belt and braces: even a library log line can never print a secret.
for handler in logging.getLogger().handlers:
    handler.addFilter(RedactSecret(config.price_api_key))
    handler.addFilter(RedactSecret(config.token_secret))
# The stream logs its own short warnings, so the library's verbose ones are muted.
logging.getLogger("websocket").setLevel(logging.CRITICAL)
logging.info(
    "Watchlist service %s starting on %s:%s", config.git_sha, config.host, config.port
)
app = create_app(config)
app.extensions["price_stream"].start()
serve(app, host=config.host, port=config.port)
