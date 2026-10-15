from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from threading import Thread
import unittest
from unittest.mock import patch

from launch import healthy


class Handler(BaseHTTPRequestHandler):
    body = b"ok"

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


class LauncherTests(unittest.TestCase):
    def test_loopback_health_ignores_system_proxy(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {"HTTP_PROXY":"http://127.0.0.1:1", "http_proxy":"http://127.0.0.1:1", "NO_PROXY":"", "no_proxy":""}):
                self.assertTrue(healthy(f"http://127.0.0.1:{server.server_port}/orr-workbench/"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_non_health_response_not_reused(self):
        class OtherHandler(Handler):
            body = b"not this service"
        server = ThreadingHTTPServer(("127.0.0.1", 0), OtherHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.assertFalse(healthy(f"http://127.0.0.1:{server.server_port}/"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
