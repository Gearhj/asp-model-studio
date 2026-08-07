"""Serve one already-built ATLAS SPA without Vite, HMR, or external writes."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


class _SpaHandler(SimpleHTTPRequestHandler):
    server_version = "ATLAS-Isolated-Static"
    sys_version = ""

    def log_message(self, _format: str, *args: object) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _requested_file_exists(self) -> bool:
        path = unquote(urlsplit(self.path).path)
        translated = Path(self.translate_path(path)).resolve(strict=False)
        root = Path(self.directory or ".").resolve(strict=True)
        if translated != root and root not in translated.parents:
            return False
        return translated.is_file()

    def _serve_spa(self, *, include_body: bool) -> None:
        original_path = self.path
        self.path = "/index.html"
        try:
            if include_body:
                super().do_GET()
            else:
                super().do_HEAD()
        finally:
            self.path = original_path

    def do_GET(self) -> None:  # noqa: N802 - stdlib protocol hook
        if self._requested_file_exists() or urlsplit(self.path).path == "/":
            super().do_GET()
            return
        self._serve_spa(include_body=True)

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib protocol hook
        if self._requested_file_exists() or urlsplit(self.path).path == "/":
            super().do_HEAD()
            return
        self._serve_spa(include_body=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve(strict=True)
    if not root.is_dir() or not (root / "index.html").is_file():
        raise SystemExit("The isolated production build is unavailable.")
    if args.port in {5174, 8001} or args.port < 1024 or args.port > 65535:
        raise SystemExit("The isolated static port is not permitted.")
    handler = partial(_SpaHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
