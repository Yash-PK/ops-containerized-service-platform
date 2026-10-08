import contextlib
import copy
import io
import json
import unittest
from unittest.mock import Mock

import valkey

from opsjobs.cache import ResultCache
from opsjobs.domain import analyze
from opsjobs.worker import process_one


class WorkerCacheTests(unittest.TestCase):
    def test_worker_completes_real_calculation_with_claim_token(self):
        repo = Mock()
        repo.claim.return_value = {
            "id": "synthetic-id",
            "lease_token": "owned-token",
            "text_content": "hello world",
        }
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(process_one(repo))
        repo.complete.assert_called_once_with("synthetic-id", "owned-token", analyze("hello world"))

    def test_no_job_has_no_write_and_invalid_job_retries_under_same_token(self):
        repo = Mock()
        repo.claim.return_value = None
        self.assertFalse(process_one(repo))
        repo.complete.assert_not_called()
        repo.claim.return_value = {"id": "id", "lease_token": "token", "text_content": ""}
        self.assertTrue(process_one(repo))
        repo.retry.assert_called_once_with("id", "token")

    def test_cache_failure_corruption_and_wrong_identifier_fall_back(self):
        cache = object.__new__(ResultCache)
        cache.client = Mock()
        cache.client.getrange.side_effect = valkey.ConnectionError("synthetic outage")
        self.assertIsNone(cache.get("id"))
        cache.client.getrange.side_effect = None
        for value in (
            "{",
            "[]",
            "x" * 16385,
            json.dumps({"id": "other", "status": "succeeded"}),
            json.dumps({"id": "id", "status": "running"}),
        ):
            cache.client.getrange.return_value = value
            self.assertIsNone(cache.get("id"))

    def test_cache_accepts_complete_record_but_rejects_corrupt_results(self):
        cache = object.__new__(ResultCache)
        cache.client = Mock()
        valid = {
            "id": "id",
            "status": "succeeded",
            "attempts": 1,
            "result": analyze("data"),
            "error_code": None,
            "created_at": "2026-10-08T00:00:00+00:00",
            "updated_at": "2026-10-08T00:00:01+00:00",
        }
        cache.client.getrange.return_value = json.dumps(valid)
        self.assertEqual(cache.get("id"), valid)
        cache.client.getrange.assert_called_with("job:id", 0, 16384)
        invalid = []
        for field in valid:
            item = copy.deepcopy(valid)
            del item[field]
            invalid.append(item)
        for field, value in (
            ("attempts", True),
            ("attempts", 4),
            ("error_code", "failed"),
            ("created_at", "not-a-time"),
            ("updated_at", "2026-10-07T00:00:01+00:00"),
            ("updated_at", "2026-10-08T00:00:01"),
            ("unexpected_private_field", "synthetic-private-content"),
        ):
            item = copy.deepcopy(valid)
            item[field] = value
            invalid.append(item)
        for field, value in (
            ("sha256", "invalid-digest"),
            ("bytes", 4097),
            ("characters", 5),
            ("words", -1),
            ("lines", float("nan")),
        ):
            item = copy.deepcopy(valid)
            item["result"][field] = value
            invalid.append(item)
        for index, item in enumerate(invalid):
            with self.subTest(case=index):
                cache.client.getrange.return_value = json.dumps(item)
                self.assertIsNone(cache.get("id"))

    def test_cache_deep_json_duplicate_fields_and_oversized_bytes_fall_back(self):
        cache = object.__new__(ResultCache)
        cache.client = Mock()
        for value in (
            "[" * 1500 + "0" + "]" * 1500,
            '{"id":"id","id":"id","status":"succeeded"}',
            "é" * 8193,
            "",
        ):
            with self.subTest(length=len(value)):
                cache.client.getrange.return_value = value
                self.assertIsNone(cache.get("id"))

    def test_only_terminal_success_is_cached_with_finite_ttl(self):
        cache = object.__new__(ResultCache)
        cache.client = Mock()
        cache.put({"id": "id", "status": "queued"})
        cache.client.set.assert_not_called()
        value = {"id": "id", "status": "succeeded", "result": analyze("data")}
        cache.put(value)
        self.assertEqual(cache.client.set.call_args.kwargs, {"ex": 60})
        cache.client.set.side_effect = valkey.ConnectionError("synthetic outage")
        cache.put(value)
