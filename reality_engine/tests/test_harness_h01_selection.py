"""Synthetic common-support and label-permutation contrast tests."""
import unittest
import numpy as np
from reality_engine.harness.run_h01_selection import contrast, VARIANTS


class SelectionContrastTests(unittest.TestCase):
    def test_ten_declared_tests(self):
        self.assertEqual(len(VARIANTS),10)

    def test_group_matched_difference_not_generic_market_return(self):
        values = np.array([.3,.3,.3,.1,.1,.1, 1.3,1.3,1.3,1.1,1.1,1.1])
        scores = np.array([2,2,2,-2,-2,-2]*2,dtype=float)
        groups = np.array([0]*6+[1]*6)
        row = contrast(values,scores,groups,np.array([625,626]),detailed=True)
        self.assertAlmostEqual(row['mean_net_excess'],.2)
        self.assertEqual(row['n_events'],12)
        self.assertEqual(row['matched_cells'],2)
        reversed_ = contrast(values,-scores,groups,np.array([625,626]))
        self.assertAlmostEqual(reversed_['mean_net_excess'],-.2)

    def test_missing_common_support_is_not_imputed(self):
        row = contrast(np.array([.1,.2,.3]),np.ones(3),np.zeros(3,dtype=int),np.array([625]))
        self.assertEqual(row['n_events'],0)
        self.assertIsNone(row['mean_net_excess'])
        self.assertEqual(row['p'],1.)

    def test_strength_boundary_and_minimum_leg_count(self):
        values = np.array([.1,.1,.1,-.1,-.1,-.1])
        scores = np.array([1,1,.99,-1,-1,-1])
        row = contrast(values,scores,np.zeros(6,dtype=int),np.array([625]),threshold=1)
        self.assertEqual(row['n_events'],0)
        scores[2]=1
        row = contrast(values,scores,np.zeros(6,dtype=int),np.array([625]),threshold=1)
        self.assertEqual(row['n_events'],6)
        self.assertAlmostEqual(row['mean_net_excess'],.2)


if __name__=='__main__':
    unittest.main()
