import copy
import json
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from tracker import directory
from university_source_registry import load_registry
from test_university_discovery import fixture
from wmt_batch_probe import (
    MANIFEST, validate_manifest, observed_bucket, published_buckets,
    control_rows, select_published, verified_own_name, probe_school,
)

class BatchTests(unittest.TestCase):
    def setUp(self):
        self.idx, self.rows = directory()
        self.game = fixture()["archive"][0]
        self.game["start_utc"] = "2026-11-24T00:00:00Z"
    def test_manifest_covers_all_24_and_both_sports(self):
        data = json.loads(MANIFEST.read_text())
        self.assertEqual(len(validate_manifest(data,self.rows,load_registry())),24)
        data["schools"].pop()
        with self.assertRaises(ValueError):
            validate_manifest(data,self.rows,load_registry())
    def test_published_bucket_rejects_unexpected_hosts_and_paths(self):
        self.assertEqual(observed_bucket("https://storage.googleapis.com/school-prod/verified.pdf"), "/school-prod/")
        for url in ("https://example.com/school-prod/verified.pdf",
                    "https://storage.googleapis.com/school-prod/../verified.pdf",
                    "https://storage.googleapis.com/school-prod/%2e%2e/verified.pdf",
                    "https://storage.googleapis.com/school-prod/verified.pdf?token=abc"):
            self.assertIsNone(observed_bucket(url))
    def test_exact_row_and_pdf_label(self):
        html = "<h1>2026-27 Women's Basketball Schedule</h1><div>Nov 23 <span>Arizona</span> Win 93-62 <a href='https://storage.googleapis.com/school-prod/a.pdf'>Box Score (PDF)</a></div>"
        controls=control_rows([self.game],"vanderbilt","WBB",self.idx)
        result,status=select_published(html,"https://vucommodores.com/sports/wbball/schedule","WBB",controls)
        self.assertEqual(status,"candidate")
        self.assertEqual(result[2],"https://storage.googleapis.com/school-prod/a.pdf")
        for broken in (html.replace("93-62","93-63"),html.replace("Nov 23","Nov 22"),html.replace("Box Score (PDF)","Game Notes"),html.replace("Women's","Men's")):
            self.assertIsNone(select_published(broken,"https://vucommodores.com/sports/wbball/schedule","WBB",controls)[0])
    def test_same_day_duplicate_control_rejected(self):
        other=copy.deepcopy(self.game)
        other["key"]="wbb:duplicate"
        self.assertFalse(control_rows([self.game,other],"vanderbilt","WBB",self.idx))
    def test_pdf_name_and_score_verified(self):
        text="Official Basketball Box Score - Final\n2026-27 Women's Basketball 11/23/26\nVanderbilt - 93 Record: 6-1\nArizona - 62 Record: 4-2"
        self.assertEqual(verified_own_name(text,"vanderbilt",self.game,"home",["Arizona"],self.idx,"WBB"),"Vanderbilt")
        self.assertIsNone(verified_own_name(text.replace("Vanderbilt","Other school"),"vanderbilt",self.game,"home",["Arizona"],self.idx,"WBB"))
        self.assertIsNone(verified_own_name(text.replace("Arizona - 62","Arizona - 61"),"vanderbilt",self.game,"home",["Arizona"],self.idx,"WBB"))
    @patch("wmt_batch_probe.get")
    def test_denial_stops_both_sports(self,get):
        get.side_effect=HTTPError("https://vucommodores.com/robots.txt",403,"Forbidden",{},None)
        item={"school":"vanderbilt","host":"vucommodores.com","paths":{"WBB":"/sports/wbball/schedule","MBB":"/sports/mbball/schedule"}}
        results=probe_school(item,[self.game],self.idx,self.rows,set())
        self.assertEqual([r["status"] for r in results],["source_unavailable","source_stopped"])
        self.assertEqual(get.call_count,1)

if __name__=="__main__":
    unittest.main()
