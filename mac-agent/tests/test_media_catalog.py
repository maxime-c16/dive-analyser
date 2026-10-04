from src.media_catalog import CATALOG_CHUNK_SIZE, CATALOG_FREE_SPACE_FLOOR, _prepare_record


def test_catalog_record_parses_exact_canonical_code_and_position():
    record = _prepare_record({"agent_local_uuid": "uuid", "raw_caption": "103B G 1m"})
    assert record["parsed_metadata"]["dive_code"] == "103B"
    assert record["parsed_metadata"]["performance"] == "G"


def test_catalog_invalid_caption_is_preserved_not_dropped():
    record = _prepare_record({"agent_local_uuid": "uuid", "raw_caption": "holiday clip"})
    assert record["raw_caption"] == "holiday clip"
    assert record["parsed_metadata"] is None


def test_catalog_limits_are_bounded():
    assert CATALOG_CHUNK_SIZE == 200
    assert CATALOG_FREE_SPACE_FLOOR == 22 * 1024**3
