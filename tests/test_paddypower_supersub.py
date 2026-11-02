"""paddypower_prices.super_sub: reads whether Super Sub applies off the game page.

The shape is the one Paddy Power's event page returned for Chelsea v Man Utd
on 31 Oct 2026 (cache/pp_event_36206188.json), cut down to the promotion parts.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paddypower_prices as pp  # noqa: E402


def page(promos, card_ids):
    return {"layout": {
        "cards": {"promotionlayoutid": {"id": "promotionlayoutid", "type": "PROMOTION",
                                        "promotions": [{"eventStatus": "ALL", "id": i, "eventId": 1} for i in card_ids]}},
        "promotions": promos}}


SUPER = {"id": 294443, "title": "SUPER SUB Your bet rolls over to the new player coming on", "body": "..."}
OTHER = {"id": 292344, "title": "Acca Boost", "body": "..."}


class SuperSubFlag(unittest.TestCase):
    def test_premier_league_page_says_yes(self):
        self.assertIs(pp.super_sub(page({"294443": SUPER, "292344": OTHER}, [292344, 294443])), True)

    def test_page_with_other_promotions_only_says_no(self):
        self.assertIs(pp.super_sub(page({"292344": OTHER}, [292344])), False)

    def test_promotion_held_but_not_on_this_game(self):
        self.assertIs(pp.super_sub(page({"294443": SUPER, "292344": OTHER}, [292344])), False)

    def test_page_without_promotions_cannot_say(self):
        self.assertIsNone(pp.super_sub({"layout": {}}))
        self.assertIsNone(pp.super_sub({}))


if __name__ == "__main__":
    unittest.main()
