from recon.domain.money import apply_bps, split_fees


def test_applies_basis_points_with_half_up_rounding():
    # Arrange: 100000 paise at 2% is exactly 2000
    gross, fee_bps = 100_000, 200

    # Act
    fee = apply_bps(gross, fee_bps)

    # Assert
    assert fee == 2_000


def test_rounds_half_up_rather_than_truncating():
    # 1005 paise at 50 bps = 5.025 -> rounds to 5
    assert apply_bps(1_005, 50) == 5
    # 1100 paise at 50 bps = 5.5 -> rounds up to 6
    assert apply_bps(1_100, 50) == 6


def test_fee_split_components_sum_back_to_gross():
    split = split_fees(1_234_567, 200, 1_800)

    assert split.net_paise + split.fee_paise + split.tax_paise == split.gross_paise


def test_rejects_negative_amount():
    try:
        apply_bps(-1, 200)
    except ValueError as exc:
        assert "non-negative" in str(exc)
    else:
        raise AssertionError("expected ValueError for negative amount")
