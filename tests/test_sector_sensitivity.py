import unittest

from app.services.sector_sensitivity import (
    get_sector_sensitivity,
    macro_impact_notes,
    sector_macro_heat_map,
)


class SectorSensitivityTests(unittest.TestCase):
    def test_get_sector_sensitivity_technology(self) -> None:
        sensitivity = get_sector_sensitivity("Technology")
        self.assertIsNotNone(sensitivity)
        self.assertEqual(sensitivity.sector, "Technology")
        self.assertLess(sensitivity.fed_rate_sensitivity, -0.5)  # Negative (hurt by rising rates)

    def test_get_sector_sensitivity_financials(self) -> None:
        sensitivity = get_sector_sensitivity("Financials")
        self.assertIsNotNone(sensitivity)
        self.assertEqual(sensitivity.sector, "Financials")
        self.assertGreater(sensitivity.fed_rate_sensitivity, 0)  # Positive (benefit from rising rates)

    def test_get_sector_sensitivity_energy(self) -> None:
        sensitivity = get_sector_sensitivity("Energy")
        self.assertIsNotNone(sensitivity)
        self.assertGreater(sensitivity.inflation_sensitivity, 0.5)  # Benefit from inflation

    def test_get_sector_sensitivity_unknown(self) -> None:
        sensitivity = get_sector_sensitivity("NonExistentSector")
        self.assertIsNone(sensitivity)

    def test_get_sector_sensitivity_none(self) -> None:
        sensitivity = get_sector_sensitivity(None)
        self.assertIsNone(sensitivity)

    def test_macro_impact_notes_tech_rising_rates(self) -> None:
        notes = macro_impact_notes("Technology", fed_rate_direction="rising")
        self.assertGreater(len(notes), 0)
        self.assertTrue(any("rising rates" in note.lower() for note in notes))

    def test_macro_impact_notes_financials_rising_rates(self) -> None:
        notes = macro_impact_notes("Financials", fed_rate_direction="rising")
        self.assertGreater(len(notes), 0)
        self.assertTrue(any("benefit" in note.lower() for note in notes))

    def test_macro_impact_notes_energy_elevated_inflation(self) -> None:
        notes = macro_impact_notes("Energy", inflation_level="elevated")
        self.assertGreater(len(notes), 0)
        self.assertTrue(any("inflation" in note.lower() for note in notes))

    def test_macro_impact_notes_industrials_weak_growth(self) -> None:
        notes = macro_impact_notes("Industrials", growth_outlook="weak")
        self.assertGreater(len(notes), 0)
        self.assertTrue(any("growth" in note.lower() or "headwind" in note.lower() for note in notes))

    def test_macro_impact_notes_empty_for_unknown_sector(self) -> None:
        notes = macro_impact_notes("UnknownSector")
        self.assertEqual(len(notes), 0)

    def test_sector_macro_heat_map_contains_all_sectors(self) -> None:
        heat_map = sector_macro_heat_map()
        self.assertGreater(len(heat_map), 0)
        self.assertIn("Technology", heat_map)
        self.assertIn("Financials", heat_map)
        self.assertIn("Energy", heat_map)

    def test_sector_macro_heat_map_has_all_sensitivity_metrics(self) -> None:
        heat_map = sector_macro_heat_map()
        tech = heat_map["Technology"]
        self.assertIn("fed_rate", tech)
        self.assertIn("inflation", tech)
        self.assertIn("growth", tech)
        self.assertIn("usd", tech)

    def test_sensitivity_values_in_valid_range(self) -> None:
        heat_map = sector_macro_heat_map()
        for sector, metrics in heat_map.items():
            for metric_name, value in metrics.items():
                self.assertGreaterEqual(value, -1.0, f"{sector} {metric_name} too low")
                self.assertLessEqual(value, 1.0, f"{sector} {metric_name} too high")

    def test_sensitivity_has_descriptions(self) -> None:
        for sector in ["Technology", "Financials", "Energy"]:
            sensitivity = get_sector_sensitivity(sector)
            self.assertIsNotNone(sensitivity.description)
            self.assertGreater(len(sensitivity.description), 10)


if __name__ == "__main__":
    unittest.main()
