"""Synthetic HTML only; no browser-export tokens, scripts, or statistics."""
import unittest
from datetime import date
from direct_ncaa import parse_scoreboard, verify_saved_box

DAY = date(2026, 11, 21)
HEAD = '<h1>2026-27 Football FBS Scoreboard</h1><select id="season_division_id_select"><option value="18904" selected>FBS</option></select><input id="game_date" value="11/21/2026"><table><thead><tr><th>Game Date</th></tr></thead><tbody>'
ROW = '<tr><td rowspan="2">11/21/2026 12:00 PM</td><td><a href="/teams/11">Alpha (4-2)</a></td><td><table><tr><td>0</td></tr></table></td><td class="totalcol">31</td></tr><tr><td><a href="/teams/22">Beta (3-3)</a></td><td class="totalcol">29</td></tr><tr><td><a href="/contests/333/box_score">Box Score</a></td></tr>'
TAIL = '</tbody></table>'
BOX = '<div class="table-responsive"><table><tr><td><a href="/teams/11">Alpha</a></td><td style="font-size:36px">31</td><td class="grey_text">11/21/2026 12:00 PM</td><td><a href="/teams/22">Beta</a></td><td style="font-size:36px">29</td></tr><tr><td><a href="/contests/333/team_stats">Team Stats</a></td></tr></table></div>'

class DirectTests(unittest.TestCase):
    def parse(self, row=ROW):
        return parse_scoreboard(HEAD + row + TAIL, DAY)

    def test_nested_rows_and_link(self):
        game, = self.parse()
        self.assertEqual(game['contest_id'], '333')
        self.assertEqual(game['url'], 'https://stats.ncaa.org/contests/333/box_score')
        self.assertEqual(game['teams'], [{'id':'11','name':'Alpha','score':31},{'id':'22','name':'Beta','score':29}])

    def test_missing_link_retained(self):
        game, = self.parse(ROW.replace('<a href="/contests/333/box_score">Box Score</a>', ''))
        self.assertIsNone(game['url'])

    def test_duplicate_contest_rejected(self):
        with self.assertRaises(ValueError):
            self.parse(ROW + ROW)

    def test_offsite_link_rejected(self):
        with self.assertRaises(ValueError):
            self.parse(ROW.replace('/contests/333/box_score','https://example.com/contests/333/box_score'))

    def test_wrong_date_and_denial_rejected(self):
        with self.assertRaises(ValueError):
            parse_scoreboard(HEAD + ROW + TAIL, date(2026,11,22))
        with self.assertRaises(ValueError):
            parse_scoreboard('<h1>Access Denied</h1>', DAY)

    def test_box_identity(self):
        game, = self.parse()
        self.assertTrue(verify_saved_box(BOX, game))
        for wrong in (BOX.replace('/333/','/444/'),BOX.replace('/teams/22','/teams/23'),BOX.replace('>29<','>28<'),BOX.replace('11/21/','11/22/')):
            self.assertFalse(verify_saved_box(wrong,game))
