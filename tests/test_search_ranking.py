import os
import sys
import unittest


APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
sys.path.insert(0, APP)
import server  # noqa: E402


class MetadataPromotionTests(unittest.TestCase):
    def test_generic_one_word_queries_keep_full_text_ranking(self):
        self.assertIsNone(server._metadata_query("bail"))
        self.assertIsNone(server._metadata_query("enforcement"))

    def test_case_names_and_citations_use_metadata_promotion(self):
        self.assertEqual(server._metadata_query("Pankaj Bansal")[0], "pankaj bansal")
        self.assertEqual(server._metadata_query("2022 SCC OnLine SC 929")[0], "2022 scc online sc 929")

    def test_distinctive_multi_word_name_is_a_direct_match(self):
        row = {
            "case_id": "case-1",
            "title": "PANKAJ BANSAL versus UNION OF INDIA & ORS.",
            "citation": "[2023] 12 S.C.R. 714",
            "case_number": "Criminal Appeal Nos. 3051-3052 of 2023",
        }
        self.assertIsNotNone(server._metadata_priority(row, "Pankaj Bansal"))


if __name__ == "__main__":
    unittest.main()
