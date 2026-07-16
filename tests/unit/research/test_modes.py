"""Unit tests for research mode presets (flat-loop agent)."""

import pytest

from src.actions.research.modes import get_mode_preset


class TestResearchModePresets:
    """Preset values for speed / balanced / quality."""

    @pytest.mark.parametrize(
        "mode,max_turns,search_k",
        [("speed", 8, 3), ("balanced", 15, 5), ("quality", 25, 8)],
    )
    def test_preset_values(self, mode, max_turns, search_k):
        preset = get_mode_preset(mode)
        assert preset.max_turns == max_turns
        assert preset.search_k == search_k

    def test_presets_have_budgets(self):
        for mode in ("speed", "balanced", "quality"):
            preset = get_mode_preset(mode)
            assert preset.token_budget > 0
            assert preset.deadline > 0

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            get_mode_preset("nonsense")
