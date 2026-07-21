import unittest

from main import collapse_multilingual_urls


class CollapseMultilingualUrlsTests(unittest.TestCase):
    def test_collapses_easemate_region_language_aliases(self):
        urls = [
            'https://www.easemate.ai/hair-color-changer',
            'https://www.easemate.ai/jp/hair-color-changer',
            'https://www.easemate.ai/tw/hair-color-changer',
            'https://www.easemate.ai/br/hair-color-changer',
            'https://www.easemate.ai/ph/hair-color-changer',
        ]

        collapsed_urls, filtered_count = collapse_multilingual_urls(urls)

        self.assertEqual(collapsed_urls, ['https://www.easemate.ai/hair-color-changer'])
        self.assertEqual(filtered_count, 4)
