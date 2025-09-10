import os
from .app import app  # or from .app import create_app


def main():
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    # if using create_app(): app = create_app()
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
