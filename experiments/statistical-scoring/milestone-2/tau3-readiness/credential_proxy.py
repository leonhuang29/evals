"""Expose ADA credentials on botocore's reserved container credential address."""

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen


class _CredentialHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        upstream = os.environ["ADA_CREDENTIALS_URL"]
        with urlopen(upstream, timeout=10) as response:
            body = response.read()

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 80), _CredentialHandler).serve_forever()
