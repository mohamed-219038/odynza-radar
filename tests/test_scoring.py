import unittest

from api.watch.scoring import SCALE, adjust


class ScoringBands(unittest.TestCase):
    def test_rival_ads_rank_high(self):
        self.assertEqual(adjust('ad', 'direct', 2)[0], 4)
        self.assertEqual(adjust('ad', 'adjacent', 1)[0], 4)
        self.assertEqual(adjust('ad', 'emerging', 1)[0], 3)
        self.assertEqual(adjust('social', 'direct', 2, from_ads_source=True)[0], 4)   # anything from the ads source
        self.assertEqual(adjust('ad', 'direct', 5), (5, ''))
        self.assertIn('rival ads from a direct rival rank 4 to 5', adjust('ad', 'direct', 2)[1])
        self.assertIn('Paid ads always count', SCALE)

    def test_other_bands(self):
        self.assertEqual(adjust('pricing', 'direct', 2)[0], 4)
        self.assertEqual(adjust('mention', 'adjacent', 5)[0], 3)    # press mentions are worth knowing, not an alarm
        self.assertEqual(adjust('offer', 'client', 5)[0], 2)        # the client's own changes stay low
        self.assertEqual(adjust('unknown', 'direct', 3), (3, ''))
