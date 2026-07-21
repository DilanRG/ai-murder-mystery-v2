"""
Launcher — Entry point for the packaged executable.
Finds a free port, starts the FastAPI server, and opens the browser.
"""
import argparse
import logging
import socket
import sys
import threading
import time
import webbrowser
from collections.abc import Sequence

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("launcher")


def _valid_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= port <= 65_535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def parse_launcher_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse launcher controls used by people and packaged smoke tests."""

    parser = argparse.ArgumentParser(description="Launch The Ashwick Trust")
    parser.add_argument(
        "--port",
        type=_valid_port,
        help="Use a specific localhost port instead of scanning 8765-8799.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the server without opening the default web browser.",
    )
    return parser.parse_args(argv)


def find_free_port(start: int = 8765, end: int = 8800) -> int:
    """Find an available port in the given range."""
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found in range {start}–{end}")


def wait_for_server(host: str, port: int, timeout: float = 15.0) -> bool:
    """Block until the server is accepting connections, or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.3)
    return False


def main(argv: Sequence[str] | None = None) -> None:
    options = parse_launcher_args(argv)
    host = "127.0.0.1"
    port = options.port or find_free_port()
    url = f"http://{host}:{port}"

    logger.info("The Ashwick Trust")
    logger.info("Starting server on %s ...", url)

    # Start uvicorn in a background thread
    def run_server():
        import uvicorn
        uvicorn.run(
            "main:app",
            host=host,
            port=port,
            log_level="info",
        )

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Wait for the server to be ready, then open browser
    if wait_for_server(host, port):
        if options.no_browser:
            logger.info("Server ready.")
        else:
            logger.info("Server ready - opening browser...")
            webbrowser.open(url)
    else:
        logger.error("Server did not start within timeout.")
        sys.exit(1)

    # Keep the main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down.")
        sys.exit(0)


if __name__ == "__main__":
    main()
