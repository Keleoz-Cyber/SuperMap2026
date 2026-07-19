from pathlib import Path

from geomodeling.microseismic.parser import classify_token, parse_dat_file, split_nul_terminator

from microseismic_fixtures import HEADER, write_dat


def test_trailing_nul_pseudo_line_excluded(tmp_path: Path):
    path = write_dat(tmp_path / "W1.dat", ["        0.050000        0.524804"])
    manifest, samples = parse_dat_file(path, "W1", "L1")
    assert manifest.nul_terminator is True
    assert manifest.nul_pseudo_line_count == 1
    assert manifest.source_record_count == 1
    assert len(samples) == 1
    assert "SOURCE_NUL_TERMINATOR" in manifest.quality_issues


def test_file_without_nul_terminator(tmp_path: Path):
    path = write_dat(tmp_path / "W1.dat", ["        0.050000        0.524804"], trailing_nul=False)
    manifest, samples = parse_dat_file(path, "W1", "L1")
    assert manifest.nul_terminator is False
    assert manifest.nul_pseudo_line_count == 0
    assert len(samples) == 1


def test_msvc_special_nan_token(tmp_path: Path):
    path = write_dat(tmp_path / "W8.dat", ["        0.050000        1.#QNAN0"])
    manifest, samples = parse_dat_file(path, "W8", "L1")
    sample = samples[0]
    assert sample.vx_raw_token == "1.#QNAN0"
    assert sample.vx_value is None
    assert sample.is_numeric_valid is False
    assert sample.included_in_valid_numeric is False
    assert sample.included_in_raw is True
    assert "SOURCE_SPECIAL_NAN_TOKEN" in sample.quality_flags
    assert manifest.invalid_numeric_count == 1
    assert manifest.valid_numeric_count == 0


def test_plain_nan_token(tmp_path: Path):
    path = write_dat(tmp_path / "W1.dat", ["        0.050000        NaN"])
    _, samples = parse_dat_file(path, "W1", "L1")
    assert samples[0].is_numeric_valid is False
    assert samples[0].invalid_reason == "nan_token"
    assert "NAN_TOKEN" in samples[0].quality_flags


def test_infinity_token(tmp_path: Path):
    path = write_dat(tmp_path / "W1.dat", ["        0.050000        Infinity"])
    _, samples = parse_dat_file(path, "W1", "L1")
    assert samples[0].is_numeric_valid is False
    assert samples[0].invalid_reason == "infinite_token"
    assert "INFINITE_TOKEN" in samples[0].quality_flags


def test_non_numeric_text_token(tmp_path: Path):
    path = write_dat(tmp_path / "W1.dat", ["        0.050000        abc"])
    _, samples = parse_dat_file(path, "W1", "L1")
    assert samples[0].is_numeric_valid is False
    assert samples[0].invalid_reason == "non_numeric_token"
    assert samples[0].vx_raw_token == "abc"


def test_empty_file(tmp_path: Path):
    path = tmp_path / "W1.dat"
    path.write_bytes(b"")
    manifest, samples = parse_dat_file(path, "W1", "L1")
    assert manifest.parse_status == "empty_file"
    assert manifest.source_record_count == 0
    assert samples == []
    assert "EMPTY_FILE" in manifest.quality_issues


def test_field_count_mismatch(tmp_path: Path):
    path = write_dat(tmp_path / "W1.dat", ["        0.050000"])
    _, samples = parse_dat_file(path, "W1", "L1")
    assert samples[0].is_numeric_valid is False
    assert "FIELD_COUNT_MISMATCH" in samples[0].quality_flags
    assert samples[0].wl_half_km_raw_token == "0.050000"
    assert samples[0].vx_raw_token is None


def test_raw_tokens_and_standardized_values_preserved(tmp_path: Path):
    path = write_dat(tmp_path / "W1.dat", ["        0.050000        0.524804"])
    manifest, samples = parse_dat_file(path, "W1", "L1")
    sample = samples[0]
    assert sample.wl_half_km_raw_token == "0.050000"
    assert sample.vx_raw_token == "0.524804"
    assert sample.wl_half_km_value == 0.05
    assert sample.vx_value == 0.524804
    assert sample.is_numeric_valid is True
    assert manifest.header_text == HEADER.strip()


def test_source_traceability(tmp_path: Path):
    path = write_dat(tmp_path / "W8.dat", ["        0.050000        1.#QNAN0", "        0.050000        0.524804"])
    _, samples = parse_dat_file(path, "W8", "L1")
    assert samples[0].sample_id == "W8:2"
    assert samples[0].source_line_number == 2
    assert samples[0].source_file_name == "W8.dat"
    assert samples[1].sample_id == "W8:3"


def test_parse_does_not_modify_source(tmp_path: Path):
    from geomodeling.io import sha256_file

    path = write_dat(tmp_path / "W1.dat", ["        0.050000        0.524804"])
    before = sha256_file(path)
    parse_dat_file(path, "W1", "L1")
    assert sha256_file(path) == before


def test_split_nul_terminator_counts():
    content, pseudo = split_nul_terminator(b"a\r\nb\r\n\x00")
    assert pseudo == 1
    assert content == b"a\r\nb"
    content, pseudo = split_nul_terminator(b"a\r\nb\r\n")
    assert pseudo == 0
    assert content == b"a\r\nb"


def test_classify_token_variants():
    assert classify_token("1.#QNAN0")[1] == "msvc_special_nan_token"
    assert classify_token("-1.#INF")[1] == "msvc_special_infinite_token"
    assert classify_token("1.#IND")[1] == "msvc_special_nan_token"
    assert classify_token("")[1] == "empty_token"
    assert classify_token("1e999")[1] == "infinite_token"
    assert classify_token("0.5")[0] == 0.5
