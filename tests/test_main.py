"""Tests for __main__ module."""

import sys
from io import BytesIO
from unittest.mock import patch

import pytest

from slskd_importer.__main__ import HealthHandler, main


class TestHealthHandler:
    def _handler(self, path: str):
        from unittest.mock import MagicMock

        handler = MagicMock(spec=HealthHandler)
        handler.path = path
        handler.wfile = BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler._json_response = lambda code, payload: HealthHandler._json_response(handler, code, payload)
        return handler

    def test_health_endpoint(self):
        """HealthHandler responds 200 on /health."""
        from slskd_importer.health.server import set_health_checker

        set_health_checker(None)
        handler = self._handler("/health")
        HealthHandler.do_GET(handler)

        handler.send_response.assert_called_once_with(200)
        handler.wfile.seek(0)
        body = handler.wfile.read()
        assert b'"status": "healthy"' in body
        assert b'"slskd": "ok"' in body

    def test_ready_endpoint(self):
        from slskd_importer.health.server import set_health_checker

        set_health_checker(None)
        handler = self._handler("/ready")
        HealthHandler.do_GET(handler)
        handler.send_response.assert_called_once_with(200)
        handler.wfile.seek(0)
        assert b'"status": "ready"' in handler.wfile.read()

    def test_health_degraded(self):
        from slskd_importer.health.server import set_health_checker

        set_health_checker(lambda: False)
        handler = self._handler("/health")
        HealthHandler.do_GET(handler)
        handler.send_response.assert_called_once_with(200)
        handler.wfile.seek(0)
        body = handler.wfile.read()
        assert b'"status": "degraded"' in body
        set_health_checker(None)

    def test_ready_unavailable(self):
        from slskd_importer.health.server import set_health_checker

        set_health_checker(lambda: False)
        handler = self._handler("/ready")
        HealthHandler.do_GET(handler)
        handler.send_response.assert_called_once_with(503)
        set_health_checker(None)

    def test_not_found(self):
        """HealthHandler responds 404 on unknown paths."""
        handler = self._handler("/unknown")
        HealthHandler.do_GET(handler)
        handler.send_response.assert_called_once_with(404)


class TestMain:
    def test_version_flag(self):
        with patch.object(sys, "argv", ["slskd-importer", "--version"]), pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

    def test_default_command_is_run(self):
        """Without a subcommand, main defaults to 'run'."""
        with patch.object(sys, "argv", ["slskd-importer"]), patch("slskd_importer.__main__.cmd_run") as mock_run:
            main()
            mock_run.assert_called_once()

    def test_run_subcommand(self):
        with (
            patch.object(sys, "argv", ["slskd-importer", "run"]),
            patch("slskd_importer.__main__.cmd_run") as mock_run,
        ):
            main()
            mock_run.assert_called_once()

    def test_unknown_command(self):
        with patch.object(sys, "argv", ["slskd-importer", "unknown"]), pytest.raises(SystemExit):
            main()
