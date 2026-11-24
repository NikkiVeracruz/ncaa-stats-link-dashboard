import unittest
from university_link_acquisition_probe import candidates

HEADER = "<h1>2026-27 Women's Basketball Schedule</h1>"
ROW = '<div><span>Mon</span><span>Nov 23</span><span>Arizona</span><span>W Win 93-62</span><a href="/boxscore/10829">Box Score</a><a href="/documents/test.pdf">Box Score (PDF)</a></div>'

class AcquisitionTests(unittest.TestCase):
    def test_exact_match(self):
        self.assertEqual(candidates(HEADER + ROW), {
            "box_score": "https://vucommodores.com/boxscore/10829",
            "pdf_candidate": "https://vucommodores.com/documents/test.pdf"})
    def test_wrong_score(self):
        self.assertEqual(candidates(HEADER + ROW.replace("93-62", "93-63")), {})
    def test_wrong_opponent(self):
        self.assertEqual(candidates(HEADER + ROW.replace("Arizona", "Arizona State")), {})
    def test_wrong_date(self):
        self.assertEqual(candidates(HEADER + ROW.replace("Nov 23", "Nov 24")), {})
    def test_other_host(self):
        self.assertNotIn("pdf_candidate", candidates(HEADER + ROW.replace("/documents/test.pdf", "https://example.com/test.pdf")))
    def test_wrong_sport(self):
        self.assertEqual(candidates(HEADER.replace("Women's", "Men's") + ROW), {})
    def test_conflicting_links(self):
        self.assertEqual(candidates(HEADER + ROW + ROW.replace("10829", "10830")), {})

if __name__ == "__main__":
    unittest.main()
