import copy
import gzip
import io
import json
import unittest
from datetime import timedelta
from email.message import Message
from unittest.mock import patch

from university_link_acquisition_probe import read_body
from university_source_registry import REGISTRY, validate_registry, unique_pairs, load_registry
from tracker import directory
from university_discovery import eligible, enrich, SOURCES
from basketball_expansion_control import fixture as new_fixture, NOW
from university_expansion_control import fixture as old_fixture
from test_university_discovery import fixture as vfixture

class Response:
    def __init__(self, body, encoding=None):
        self.stream = io.BytesIO(body)
        self.headers = Message()
        if encoding is not None:
            self.headers["Content-Encoding"] = encoding
    def read(self, n):
        return self.stream.read(n)

class ResponseTests(unittest.TestCase):
    def test_identity_and_gzip(self):
        payload = b"valid public schedule"
        self.assertEqual(read_body(Response(payload), 100), payload)
        self.assertEqual(read_body(Response(gzip.compress(payload), "gzip"), 100), payload)
        self.assertEqual(read_body(Response(gzip.compress(payload)), 100), payload)
    def test_wire_limit(self):
        with self.assertRaises(ValueError):
            read_body(Response(b"x"*101), 100)
    def test_decoded_limit(self):
        with self.assertRaises(ValueError):
            read_body(Response(gzip.compress(b"x"*10000), "gzip"), 100)
    def test_corrupt_and_unknown_encoding(self):
        for response in (Response(b"bad gzip", "gzip"), Response(b"plain", "br"), Response(gzip.compress(b"text")[:-4], "gzip")):
            with self.assertRaises(ValueError):
                read_body(response, 100)

class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(REGISTRY.read_text())
        _, self.rows = directory()
    def test_five_verified_combinations(self):
        self.assertEqual(sum(len(x) for x in load_registry().values()), 5)
        self.assertEqual(set(SOURCES["san_jose_state"]), {"MBB"})
        self.assertEqual(set(SOURCES["vanderbilt"]), {"WBB"})
    def test_invalid_host_bucket_or_evidence(self):
        for field, value in (("host","example.test"), ("prefix","/../"), ("platform","other")):
            data = copy.deepcopy(self.data)
            data["schools"]["iowa"][field] = value
            with self.assertRaises(ValueError):
                validate_registry(data,self.rows)
        self.data["schools"]["iowa"]["sports"]["WBB"]["status"]="pending"
        with self.assertRaises(ValueError):
            validate_registry(self.data,self.rows)
    def test_duplicate_json_key(self):
        with self.assertRaises(ValueError):
            json.loads('{"a":1,"a":2}', object_pairs_hook=unique_pairs)
    def test_wrong_sport_evidence(self):
        self.data["schools"]["iowa"]["sports"]["WBB"]["control"]="mbb:123"
        with self.assertRaises(ValueError):
            validate_registry(self.data,self.rows)

def combined():
    rows = new_fixture()["archive"] + old_fixture()["archive"] + vfixture()["archive"]
    return {"archive_start":"2026-11-23","current":copy.deepcopy(rows),"archive":rows}

class QueueTests(unittest.TestCase):
    def test_five_school_capacity_and_archive_integrity(self):
        feed=combined()
        before=copy.deepcopy(feed["archive"])
        calls=[]
        def no_pdf(g, side):
            calls.append(g["school_keys"][side])
        enrich(feed,NOW,no_pdf)
        self.assertEqual(len(set(calls)),5)
        self.assertEqual(feed["archive"],before)
        self.assertEqual(feed["current"],before)
        self.assertFalse(eligible(feed,NOW))
    def test_fair_rotation_across_slots(self):
        feed=combined()
        calls=[]
        def no_pdf(g, side):
            calls.append(g["school_keys"][side])
        with patch("university_discovery.MAX_SOURCES_PER_RUN",2):
            enrich(feed,NOW,no_pdf)
            enrich(feed,NOW+timedelta(hours=1),no_pdf)
            enrich(feed,NOW+timedelta(hours=2),no_pdf)
        self.assertEqual(len(set(calls[:5])),5)
        self.assertEqual(len(calls),6)
    def test_budget_defers_without_consuming_slots(self):
        feed=combined()
        times=iter([0,0,121])
        calls=[]
        enrich(feed,NOW,lambda g,side:calls.append(g["key"]),clock=lambda:next(times))
        self.assertEqual(len(calls),1)
        self.assertEqual(len(eligible(feed,NOW)),4)
        self.assertEqual(feed["university_discovery"]["queue"]["deferred_games"],4)
    def test_recent_completion_breaks_ties(self):
        feed=combined()
        first=eligible(feed,NOW)[0][0]
        self.assertEqual(first["final_seen_at"],max(g["final_seen_at"] for g in feed["archive"]))
    def test_blocked_school_not_reenabled(self):
        feed=combined()
        feed["university_discovery"]={"blocked_sources":{"iowa":"403"}}
        self.assertEqual(len(eligible(feed,NOW)),4)
        self.assertNotIn("iowa",[g["school_keys"][s] for g,s,_ in eligible(feed,NOW)])

if __name__ == "__main__":
    unittest.main()
