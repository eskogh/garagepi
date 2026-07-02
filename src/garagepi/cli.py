import logging
import os
from .app import app, start_runtime


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    if not debug or os.getenv("WERKZEUG_RUN_MAIN") == "true":
        start_runtime()
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
