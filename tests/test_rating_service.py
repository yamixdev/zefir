from bot.services.rating_service import reward_for_place


def test_ranked_reward_tiers():
    assert reward_for_place(1, 1300, 12) == (1000, "season_crown_legend")
    assert reward_for_place(3, 1200, 8) == (600, "season_medal_epic")
    assert reward_for_place(10, 1050, 5) == (300, "season_badge_rare")
    amount, item_code = reward_for_place(25, 1000, 4)
    assert 25 <= amount <= 250
    assert item_code is None
