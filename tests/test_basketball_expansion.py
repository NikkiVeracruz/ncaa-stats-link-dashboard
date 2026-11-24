import copy
import unittest
from basketball_expansion_control import fixture, NOW
from university_discovery import eligible, enrich, source_for
from university_link_acquisition_probe import candidates, pdf_identity

class BasketballExpansionTests(unittest.TestCase):
    def test_sport_specific_eligibility_and_preservation(self):
        feed = fixture()
        before = copy.deepcopy(feed["archive"])
        self.assertEqual(len(eligible(feed, NOW)), 2)
        def verified(g, side):
            return {"kind": "pdf_box_score", "url": "https://example.test/" + g["key"] + ".pdf"}
        enrich(feed, NOW, verified)
        self.assertEqual(feed["archive"], feed["current"])
        self.assertTrue(all(g["reports"] for g in feed["archive"]))
        for a,b in zip(feed["archive"], before):
            self.assertEqual({k:v for k,v in a.items() if k!="reports"}, {k:v for k,v in b.items() if k!="reports"})

    def test_unvalidated_sport_is_ineligible(self):
        feed = fixture()
        for g in feed["current"] + feed["archive"]:
            g["sports"] = ["WBB" if g["sports"] == ["MBB"] else "MBB"]
        self.assertFalse(eligible(feed, NOW))

    def test_cross_sport_same_day_is_not_duplicate(self):
        feed = fixture()
        same = dict(feed["archive"][0], key="mbb:other", sports=["MBB"])
        feed["archive"].append(same)
        self.assertEqual(len(eligible(feed, NOW)), 2)

    def test_wrong_sport_pdf_rejected(self):
        text = "Official Basketball Box Score - Final 2026-27 Men's Basketball 11/23/26 San Jose St. - 88 Record: 4-3 UC San Diego - 79 Record: 3-3"
        kw = dict(opponent="UC San Diego",day="11/23/26",own_score=88,opponent_score=79,season="2026-27",own_name="San Jose St.")
        self.assertTrue(pdf_identity(text, sport="MBB", **kw))
        self.assertFalse(pdf_identity(text, sport="WBB", **kw))
        self.assertFalse(pdf_identity(text.replace("79 Record", "78 Record"), sport="MBB", **kw))

    def test_compact_date_and_prefix_label(self):
        html = "<h1>2026-27 Men's Basketball Schedule</h1><div><span>Mon, Nov23</span><span>UC San Diego</span><span>W Win 88-79</span><a href='https://storage.googleapis.com/san-jose-state-prod/test.pdf'>Opens in a new window Box Score (PDF)</a></div>"
        kw = dict(opponent="UC San Diego",result="Win 88-79",sport="MBB",compact_date=True,source="https://sjsuspartans.com/sports/mens-basketball/schedule",cdn_prefix="/san-jose-state-prod/")
        self.assertIn("pdf_candidate", candidates(html, **kw))
        self.assertFalse(candidates(html.replace("Nov23","Nov24"), **kw))
        self.assertFalse(candidates(html.replace("Men's","Women's"), **kw))

    def test_repeated_same_date_not_other_date(self):
        html = "<h1>2026-27 Women's Basketball Schedule</h1><div><span>Nov 23</span><span>Nov 23</span><span>Belmont</span><span>W Win 103-45</span><a href='https://storage.googleapis.com/lsusports-net-prod/test.pdf'>Box Score (.pdf)</a></div>"
        kw = dict(opponent="Belmont",result="Win 103-45",repeat_date=True,source="https://lsusports.net/sports/wbball/schedule",cdn_prefix="/lsusports-net-prod/",pdf_labels=("box score (.pdf)",))
        self.assertIn("pdf_candidate", candidates(html, **kw))
        self.assertFalse(candidates(html.replace("<span>Nov 23</span><span>Nov 23</span>","<span>Nov 23</span><span>Nov 24</span>"), **kw))
        self.assertFalse(candidates(html.replace("103-45","103-46"), **kw))

if __name__ == "__main__":
    unittest.main()
