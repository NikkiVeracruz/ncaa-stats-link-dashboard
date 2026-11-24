import copy
import unittest
from datetime import timedelta
from urllib.error import HTTPError
from unittest.mock import patch

from university_discovery import eligible, enrich, acquire, SOURCES
from university_link_acquisition_probe import candidates, pdf_identity, cdn_allowed
from university_expansion_control import fixture, NOW

class ExpansionTests(unittest.TestCase):
    def test_two_distinct_sources_and_both_views(self):
        feed = fixture()
        before = copy.deepcopy(feed["archive"])
        def verified(g, side):
            return {"kind":"pdf_box_score", "url":"https://storage.googleapis.com" + SOURCES[g["school_keys"][side]][g["sports"][0]]["prefix"] + "test.pdf", "side":side}
        enrich(feed, NOW, verified)
        self.assertEqual(len([g for g in feed["archive"] if g["reports"]]), 2)
        self.assertEqual(feed["archive"], feed["current"])
        for a,b in zip(feed["archive"],before):
            self.assertEqual({k:v for k,v in a.items() if k!="reports"}, {k:v for k,v in b.items() if k!="reports"})
        self.assertFalse(eligible(feed, NOW + timedelta(hours=1)))

    def test_one_school_denial_does_not_disable_others(self):
        feed = fixture()
        def get(g, side):
            if g["school_keys"][side] == "iowa":
                raise HTTPError("https://hawkeyesports.com", 403, "Forbidden", {}, None)
            return {"kind":"pdf_box_score", "url":"https://example.test/verified.pdf"}
        enrich(feed, NOW, get)
        self.assertIn("iowa", feed["university_discovery"]["blocked_sources"])
        self.assertFalse(feed["archive"][0]["reports"])
        self.assertTrue(all(g["reports"] for g in feed["archive"][1:]))
        self.assertFalse(eligible(feed, NOW+timedelta(hours=1)))

    def test_migrate_existing_vanderbilt_slot_without_recheck(self):
        from test_university_discovery import fixture as vfixture
        feed = vfixture()
        from link_enrichment import slot
        feed["university_discovery"] = {"slots": {feed["archive"][0]["key"]: list(slot(feed["archive"][0], NOW))}}
        self.assertFalse(eligible(feed, NOW))

    def test_direct_pdf_only_from_school_bucket(self):
        url = "https://storage.googleapis.com/hawkeyesports-prod/test.pdf"
        html = "<h1>2026-27 Women's Basketball Schedule</h1><div><span>Nov 23</span><span>Utah</span><span>W Win 75-66</span><a href='" + url + "'>Box Score (PDF)</a></div>"
        kw = dict(opponent="Utah", result="Win 75-66", source="https://hawkeyesports.com/sports/wbball/schedule", cdn_prefix="/hawkeyesports-prod/")
        self.assertEqual(candidates(html, **kw)["pdf_candidate"], url)
        self.assertFalse(candidates(html.replace("hawkeyesports-prod","other-bucket"), **kw))
        self.assertFalse(cdn_allowed(url.replace("test.pdf","../other.pdf"), "/hawkeyesports-prod/"))
        self.assertFalse(cdn_allowed(url.replace("test.pdf","%2e%2e/other.pdf"), "/hawkeyesports-prod/"))

    def test_unverified_school_is_not_enabled(self):
        self.assertNotIn("northwestern", SOURCES)
        self.assertNotIn("virginia_tech", SOURCES)

    def test_virginia_tech_short_result(self):
        html = "<h1>Women's Basketball 2026-27 Schedule</h1><div><span>Nov 23</span><span>UT Martin</span><span>W 85-41</span><a href='/documents/control.pdf'>Box Score (PDF)</a></div>"
        kw = dict(opponent="UT Martin",result="Win 85-41",source="https://hokiesports.com/sports/womens-basketball/schedule",heading_order="sport_first",short_result=True)
        self.assertIn("pdf_candidate", candidates(html, **kw))
        self.assertFalse(candidates(html.replace("W 85-41","L 85-41"), **kw))

    def test_miami_gamebook_and_exact_named_scores(self):
        html = "<h1>2026-27 Women's Basketball Schedule</h1><div><span>Nov 23</span><span>Michigan</span><span>L Loss 58-79</span><a href='/documents/control.pdf'>Gamebook</a></div>"
        kw = dict(opponent="Michigan", result="Loss 58-79", source="https://miamihurricanes.com/sports/wbball/schedule", pdf_labels=("box score (pdf)","gamebook"))
        self.assertIn("pdf_candidate",candidates(html,**kw))
        text = "Official Basketball Box Score - Final 2026-27 Women's Basketball 11/23/26 Miami (FL) - 58 Record: 6-1 Michigan - 79 Record: 6-0"
        args=dict(opponent="Michigan",day="11/23/26",own_score=58,opponent_score=79,season="2026-27",own_name="Miami (FL)")
        self.assertTrue(pdf_identity(text,**args))
        self.assertFalse(pdf_identity(text.replace("Miami (FL)","Miami (OH)"),**args))
        self.assertFalse(pdf_identity(text.replace("Michigan - 79","Michigan - 78"),**args))

if __name__ == "__main__":
    unittest.main()
