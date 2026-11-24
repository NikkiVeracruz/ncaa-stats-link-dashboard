import unittest
from university_link_acquisition_probe import candidates, download_link, pdf_identity

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

class PDFVerificationTests(unittest.TestCase):
    def test_unique_published_download(self):
        url = "https://storage.googleapis.com/vucommodores-prod/2026/11/report.pdf"
        self.assertEqual(download_link(f'<a href="{url}">Download PDF</a>', "https://vucommodores.com/documents/test.pdf"), url)
        self.assertIsNone(download_link('<a href="https://storage.googleapis.com/other/report.pdf">Download PDF</a>', "https://vucommodores.com/documents/test.pdf"))
    def test_identity_requires_labeled_final_report(self):
        text = "Official Basketball Box Score - Final 2026-27 Women's Basketball 11/23/26 Vanderbilt - 93 Record: 6-1 Arizona - 62 Record: 4-2"
        args = dict(opponent="Arizona", day="11/23/26", own_score=93, opponent_score=62, season="2026-27")
        self.assertTrue(pdf_identity(text, **args))
        self.assertFalse(pdf_identity(text.replace("Arizona - 62", "Arizona - 63"), **args))
        self.assertFalse(pdf_identity(text.replace("11/23/26", "11/24/26"), **args))
        self.assertFalse(pdf_identity(text.replace("Final", "Unofficial"), **args))

if __name__ == "__main__":
    unittest.main()
