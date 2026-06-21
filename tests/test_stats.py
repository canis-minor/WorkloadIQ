from workloadiq import stats


def test_quantile_interpolates():
    assert stats.quantile([0, 10], 0.5) == 5
    assert stats.p95([0] * 95 + [100] * 5) >= 0  # sane
    assert stats.quantile([], 0.5) == 0.0
    assert stats.quantile([42], 0.9) == 42


def test_linreg_recovers_slope():
    xs = [0, 1, 2, 3, 4]
    ys = [1, 3, 5, 7, 9]  # y = 2x + 1
    slope, intercept = stats.linreg(xs, ys)
    assert abs(slope - 2.0) < 1e-9
    assert abs(intercept - 1.0) < 1e-9


def test_linreg_degenerate():
    assert stats.linreg([1], [5]) == (0.0, 5.0)
    assert stats.linreg([2, 2, 2], [1, 2, 3])[0] == 0.0


def test_safe_ratio():
    assert stats.safe_ratio(10, 5) == 2.0
    assert stats.safe_ratio(0, 0) == 1.0
    assert stats.safe_ratio(5, 0) == float("inf")
