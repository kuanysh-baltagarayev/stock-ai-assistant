from __future__ import annotations

import asyncio
import io
import json
import logging
from types import SimpleNamespace
import unittest

from app.logging_config import configure_logging
from app.main import log_requests


class LoggingConfigTests(unittest.TestCase):
    def test_configure_logging_emits_structured_json(self) -> None:
        stream = io.StringIO()
        configure_logging(force=True, stream=stream)
        logger = logging.getLogger("app.tests")

        logger.info("example_event", extra={"component": "test", "ticker": "AAPL"})

        payload = json.loads(stream.getvalue().strip())
        self.assertEqual(payload["message"], "example_event")
        self.assertEqual(payload["component"], "test")
        self.assertEqual(payload["ticker"], "AAPL")
        self.assertEqual(payload["logger"], "app.tests")

    def test_api_request_middleware_logs_completion(self) -> None:
        stream = io.StringIO()
        configure_logging(force=True, stream=stream)

        request = SimpleNamespace(method="GET", url=SimpleNamespace(path="/health"))

        async def call_next(_: object) -> SimpleNamespace:
            return SimpleNamespace(status_code=200)

        asyncio.run(log_requests(request, call_next))

        payload = json.loads(stream.getvalue().strip())
        self.assertEqual(payload["message"], "request_completed")
        self.assertEqual(payload["method"], "GET")
        self.assertEqual(payload["path"], "/health")
        self.assertEqual(payload["status_code"], 200)
        self.assertEqual(payload["component"], "api")
