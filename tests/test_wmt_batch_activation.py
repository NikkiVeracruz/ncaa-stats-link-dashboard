import unittest
import copy
import json
from datetime import timedelta
from university_discovery import eligible, enrich, SOURCES
from wmt_batch_activation_control import cases, fixture, RESULTS

class ActivationTests(unittest.TestCase):
    def test_all_48_outcomes_and_exactly_seven_promotions(self):
        results=json.loads(RESULTS.read_text())["results"]
        self.assertEqual(len(results),48)
        self.assertEqual(len({(r["school"],r["sport"]) for r in results}),48)
        self.assertEqual(len(cases()),7)
        for r in results:
            self.assertEqual(r["sport"] in SOURCES.get(r["school"],{}), r["status"]=="verified")

    def test_config_and_queue_match_each_control(self):
        for r in cases():
            feed, now = fixture(r)
            before=copy.deepcopy(feed["archive"][0])
            due=eligible(feed,now)
            self.assertEqual(len(due),1)
            self.assertEqual(due[0][1],r["side"])
            cfg=SOURCES[r["school"]][r["sport"]]
            self.assertEqual(cfg["prefix"],r["prefix"])
            self.assertEqual(cfg["path"],r["config"]["path"])
            self.assertEqual(cfg["control"],r["control"])
            report={"kind":"pdf_box_score","url":r["pdf"],"verification":"automatic_final_pdf_identity"}
            enrich(feed,now,lambda g,s:report)
            self.assertEqual(feed["current"],feed["archive"])
            self.assertEqual(feed["archive"][0]["reports"],[report])
            self.assertEqual({k:v for k,v in feed["archive"][0].items() if k!="reports"},{k:v for k,v in before.items() if k!="reports"})
            self.assertFalse(eligible(feed,now+timedelta(minutes=5)))

    def test_no_historical_import(self):
        for r in cases():
            feed, now=fixture(r)
            feed["archive_start"]="2026-11-23"
            self.assertFalse(eligible(feed,now))
            self.assertIsNone(enrich(feed,now,lambda g,s:self.fail("Historical source must not be fetched")))

if __name__ == "__main__":
    unittest.main()
