from jobs.tax_labels import resolve_tax_summary_labels


def test_resolves_state_plus_metro():
    rows = [
        {
            "state_name": "Oregon",
            "state_abbreviation": "OR",
            "display_label": None,
            "sentence": "state",
        },
        {
            "state_name": "Oregon Metro Supportive Housing Services",
            "state_abbreviation": "OR",
            "display_label": "OR Metro Income Tax",
            "sentence": "metro",
        },
    ]

    assert resolve_tax_summary_labels(rows) == [
        "State Income Tax",
        "OR Metro Income Tax",
    ]


def test_legacy_single_state_stays_generic():
    rows = [
        {
            "state_name": "California",
            "state_abbreviation": "CA",
            "sentence": "refund",
        }
    ]

    assert resolve_tax_summary_labels(rows) == ["State Income Tax"]


def test_explicit_state_label_is_supported_defensively():
    rows = [{"display_label": " State Income Tax: ", "sentence": "refund"}]

    assert resolve_tax_summary_labels(rows) == ["State Income Tax"]


def test_legacy_true_multi_state_stays_abbreviated():
    rows = [
        {
            "state_name": "California",
            "state_abbreviation": "CA",
            "sentence": "due",
        },
        {
            "state_name": "North Carolina",
            "state_abbreviation": "NC",
            "sentence": "refund",
        },
    ]

    assert resolve_tax_summary_labels(rows) == [
        "CA State Income Tax",
        "NC State Income Tax",
    ]


def test_normalizes_explicit_label_and_falls_back_after_colon_only():
    rows = [
        {
            "state_name": "Metro",
            "state_abbreviation": "OR",
            "display_label": "  OR Metro Income Tax::  ",
            "sentence": "x",
        },
        {
            "state_name": "Oregon",
            "state_abbreviation": "OR",
            "display_label": " : ",
            "sentence": "y",
        },
    ]

    assert resolve_tax_summary_labels(rows) == [
        "OR Metro Income Tax",
        "State Income Tax",
    ]


def test_invalid_labels_and_missing_names_use_safe_fallbacks():
    rows = [
        {"display_label": 123, "sentence": "x"},
        {
            "state_name": "",
            "state_abbreviation": None,
            "display_label": "",
            "sentence": "y",
        },
    ]

    assert resolve_tax_summary_labels(rows) == [
        "State Income Tax",
        "State Income Tax",
    ]


def test_multi_state_missing_or_blank_abbreviations_fall_back_to_state_name():
    rows = [
        {"state_name": "Oregon", "sentence": "a"},
        {"state_name": "Washington", "state_abbreviation": None, "sentence": "b"},
        {"state_name": "Nevada", "state_abbreviation": "", "sentence": "c"},
        {"state_name": "Arizona", "state_abbreviation": "   ", "sentence": "d"},
    ]

    assert resolve_tax_summary_labels(rows) == [
        "Oregon State Income Tax",
        "Washington State Income Tax",
        "Nevada State Income Tax",
        "Arizona State Income Tax",
    ]


def test_empty_sentence_row_still_participates_in_legacy_count():
    rows = [
        {
            "state_name": "California",
            "state_abbreviation": "CA",
            "sentence": "shown",
        },
        {
            "state_name": "North Carolina",
            "state_abbreviation": "NC",
            "sentence": "",
        },
    ]

    assert resolve_tax_summary_labels(rows) == [
        "CA State Income Tax",
        "NC State Income Tax",
    ]
