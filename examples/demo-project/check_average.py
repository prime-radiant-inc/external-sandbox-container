"""Run inside the sandbox with: python3 check_average.py."""

import unittest

from average import average


class AverageChecks(unittest.TestCase):
    def test_fractional_result(self):
        self.assertEqual(average([1, 2]), 1.5)

    def test_negative_values(self):
        self.assertEqual(average([-2, -1]), -1.5)

    def test_single_value(self):
        self.assertEqual(average([7]), 7)

    def test_empty_values(self):
        with self.assertRaises(ValueError):
            average([])


if __name__ == "__main__":
    unittest.main()
