"""Backend API server entry point for PalModManager."""
import argparse
import os
import sys
import threading


def create_app():
    """Create and configure the Flask application."""
    from flask import Flask, jsonify
    from .api_routes import api

    app = Flask(__name__)
    app.register_blueprint(api)

    @app.errorhandler(Exception)
    def handle_exception(e):
        return jsonify({"error": str(e)}), 500

    return app


def main():
    parser = argparse.ArgumentParser(description="PalModManager backend API")
    parser.add_argument("--port", type=int, default=0, help="Port to listen on (0 for ephemeral)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind to")
    args = parser.parse_args()

    # Ensure project root is on path when running as script
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    app = create_app()

    # When port is 0, Flask will choose a free port. We need to report it.
    if args.port == 0:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((args.host, 0))
        port = s.getsockname()[1]
        s.close()
        args.port = port

    # Print a startup line the frontend can parse
    print(f"PALMOD_BACKEND_PORT={args.port}", flush=True)

    _start_parent_watchdog()
    app.run(host=args.host, port=args.port, threaded=True)


def _start_parent_watchdog():
    """Exit when stdin closes, which the frontend triggers by terminating.

    The C# host redirects stdin to a pipe and closes it when the app shuts
    down (or crashes). Reading EOF is the signal to stop, so no orphaned
    backend process is left behind.
    """
    def _watch():
        stream = getattr(sys, "stdin", None)
        if stream is None or not hasattr(stream, "read"):
            return
        try:
            stream.read()
        except Exception:
            return
        os._exit(0)

    threading.Thread(target=_watch, daemon=True).start()


if __name__ == "__main__":
    main()
