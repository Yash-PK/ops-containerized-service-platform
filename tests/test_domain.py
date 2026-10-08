import hashlib
import unittest

from opsjobs.domain import InvalidInput, analyze, idempotency_key, job_id, payload


class DomainTests(unittest.TestCase):
    def test_analysis_is_content_derived_and_unicode_aware(self):
        text = "Linux café\nwork completed."
        self.assertEqual(
            analyze(text),
            {
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
                "bytes": 27,
                "characters": len(text),
                "words": 4,
                "lines": 2,
            },
        )

    def test_input_rejects_shape_type_empty_nul_surrogate_and_byte_overflow(self):
        for value in (
            [],
            {},
            {"text": 1},
            {"text": "  "},
            {"text": "x", "cmd": "no"},
            {"text": "x\x00"},
            {"text": "\ud800"},
            {"text": "é" * 2049},
        ):
            with self.subTest(value=repr(value)), self.assertRaises(InvalidInput):
                payload(value)
        self.assertEqual(payload({"text": "é" * 2048}), "é" * 2048)

    def test_key_and_identifier_are_explicitly_bounded(self):
        for value in (None, "short", "a" * 81, "invalid key", "key\nnewline"):
            with self.subTest(value=value), self.assertRaises(InvalidInput):
                idempotency_key(value)
        self.assertEqual(idempotency_key("synthetic-key-001"), "synthetic-key-001")
        identifier = "00000000-0000-4000-8000-000000000001"
        self.assertEqual(job_id(identifier), identifier)
        for value in (None, identifier.replace("-", ""), "not-a-uuid"):
            with self.assertRaises(InvalidInput):
                job_id(value)
