import pytest
from hypothesis import given, strategies as st

from pinux.capture.geometry import scale_to_image


def test_identity_scale():
    assert scale_to_image((10, 20, 30, 40), (100, 100), (100, 100)) == (10, 20, 30, 40)


def test_hidpi_double_scale():
    # widget 1920x1080 logis menampilkan citra 3840x2160 fisik
    assert scale_to_image((100, 50, 200, 100), (1920, 1080), (3840, 2160)) == (200, 100, 400, 200)


def test_non_uniform_scale_and_clamp():
    left, top, w, h = scale_to_image((90, 90, 50, 50), (100, 100), (200, 400))
    assert (left, top) == (180, 360) and (w, h) == (20, 40)  # dijepit ke tepi citra


@pytest.mark.parametrize("wsize,isize", [((0, 10), (10, 10)), ((10, 10), (10, 0))])
def test_invalid_sizes_raise(wsize, isize):
    with pytest.raises(ValueError):
        scale_to_image((0, 0, 1, 1), wsize, isize)


@given(
    x=st.floats(-500, 3000), y=st.floats(-500, 3000),
    w=st.floats(0, 3000), h=st.floats(0, 3000),
)
def test_result_always_inside_image(x, y, w, h):
    left, top, rw, rh = scale_to_image((x, y, w, h), (1920, 1080), (3840, 2160))
    assert 0 <= left and 0 <= top and rw >= 0 and rh >= 0
    assert left + rw <= 3840 + 1e-6 and top + rh <= 2160 + 1e-6
