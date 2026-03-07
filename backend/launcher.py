"""
Launcher — Entry point for the packaged executable.
Finds a free port, starts the FastAPI server, and opens the browser.
"""
import logging
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("launcher")


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


def main() -> None:
    host = "127.0.0.1"
    port = find_free_port()
    url = f"http://{host}:{port}"

    logger.info("🔪 AI Murder Mystery v2")
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
        logger.info("✅ Server ready — opening browser...")
        webbrowser.open(url)
    else:
        logger.error("❌ Server did not start within timeout.")
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
