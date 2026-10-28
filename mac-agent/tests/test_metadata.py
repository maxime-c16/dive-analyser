"""Tests for Photos caption metadata parsing."""

from src.metadata import parse_dive_caption, parse_video_label


def test_parse_open_pike_single_performance():
    metadata = parse_dive_caption("201BO M")

    assert metadata is not None
    assert metadata.dive_code == "201B"
    assert metadata.performance == "M"
    assert metadata.height == "1m"


def test_parse_open_pike_two_phase_with_height():
    metadata = parse_dive_caption("103BO G/M 3m")

    assert metadata is not None
    assert metadata.dive_code == "103B"
    assert metadata.phase1_performance == "G"
    assert metadata.phase2_performance == "M"
    assert metadata.height == "3m"


def test_regular_pike_still_parses():
    metadata = parse_dive_caption("103B G/M 3m")

    assert metadata is not None
    assert metadata.dive_code == "103B"


def test_second_token_b_is_performance_not_position_for_pike():
    metadata = parse_dive_caption("103B B")

    assert metadata is not None
    assert metadata.dive_code == "103B"
    assert metadata.performance == "B"


def test_second_token_b_is_performance_not_position_for_tuck():
    metadata = parse_dive_caption("103C B")

    assert metadata is not None
    assert metadata.dive_code == "103C"
    assert metadata.performance == "B"


def test_bare_dive_family_does_not_parse_as_exact_dive():
    assert parse_dive_caption("103 G") is None


def test_drill_tokens_are_not_people():
    metadata = parse_dive_caption("103BO G/M 3m SD")

    assert metadata is not None
    assert metadata.person_name is None
    assert metadata.modifiers == ["SD"]


def test_double_bounce_token_is_not_person():
    metadata = parse_dive_caption("201B M DB")

    assert metadata is not None
    assert metadata.person_name is None
    assert metadata.modifiers == ["DB"]


def test_hands_up_token_is_modifier():
    metadata = parse_dive_caption("103B G/M 3m HU")

    assert metadata is not None
    assert metadata.person_name is None
    assert metadata.modifiers == ["HU"]


def test_modifiers_can_precede_score():
    metadata = parse_dive_caption("103B SD HU G/M 1m")

    assert metadata is not None
    assert metadata.dive_code == "103B"
    assert metadata.phase1_performance == "G"
    assert metadata.phase2_performance == "M"
    assert metadata.height == "1m"
    assert metadata.modifiers == ["SD", "HU"]


def test_sync_is_not_modifier():
    metadata = parse_dive_caption("101B G 1m SYNC")

    assert metadata is not None
    assert metadata.is_sync is True
    assert metadata.modifiers == []


def test_double_bounce_sync_keeps_separate_concepts():
    metadata = parse_dive_caption("101B G 1m DB SYNC")

    assert metadata is not None
    assert metadata.is_sync is True
    assert metadata.modifiers == ["DB"]


def test_person_only_caption_becomes_label():
    label = parse_video_label("PAUL")

    assert label is not None
    assert label.label_type == "person"
    assert label.label_value == "PAUL"


def test_drill_only_caption_becomes_drill_label():
    label = parse_video_label("SD")

    assert label is not None
    assert label.label_type == "drill"
    assert label.label_value == "SD"


def test_reserved_single_token_does_not_become_label():
    assert parse_video_label("SMACK") is None


# ---------------------------------------------------------------------------
# DIVER_ID_19_PHANTOM_REPAIR regression tests (Subject Resolution V1)
# Root cause: "_is_person_name()" accepted the all-caps annotation token "RIP"
# (rip entry), which then auto-created a phantom diver. Captions are typed in
# ALL CAPS in production, so caps rejection is NOT the fix; RIP is a reserved
# annotation token instead.
# ---------------------------------------------------------------------------


def test_rip_token_in_dive_caption_is_not_person():
    metadata = parse_dive_caption("101B G/P 5m RIP")

    assert metadata is not None
    assert metadata.dive_code == "101B"
    assert metadata.person_name is None


def test_rip_after_sync_token_is_not_person():
    metadata = parse_dive_caption("101B G 1m SYNC RIP")

    assert metadata is not None
    assert metadata.is_sync is True
    assert metadata.person_name is None


def test_rip_alone_is_not_person_label():
    assert parse_video_label("RIP") is None


def test_real_all_caps_person_names_still_parse():
    for name in ("TOM", "PAUL", "EMI", "FANNY", "SARA", "MAT"):
        metadata = parse_dive_caption(f"101B P {name}")

        assert metadata is not None
        assert metadata.person_name == name


def test_real_all_caps_person_labels_still_parse():
    label = parse_video_label("FANNY")

    assert label is not None
    assert label.label_type == "person"
    assert label.label_value == "FANNY"


def test_sync_names_are_not_single_owner_metadata():
    for caption in ['103B G 3m SYNC MAT', '103B G 3m MAT SYNC',
                    '103B G 3m SYNC MAT+SARA', '103B G 3m SYNC']:
        metadata = parse_dive_caption(caption)
        assert metadata and metadata.is_sync and metadata.person_name is None
