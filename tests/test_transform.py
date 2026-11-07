import math

import pytest

np = pytest.importorskip("numpy")

from app.scene.load import Splats  # noqa: E402
from app.scene.transform import (  # noqa: E402
    matrix_to_quaternion,
    multiply_quaternions,
    transform_splats,
)

TURN = np.array(
    [
        [math.cos(0.5), 0, math.sin(0.5)],
        [0, 1, 0],
        [-math.sin(0.5), 0, math.cos(0.5)],
    ]
)


def quaternion_to_matrix(quaternion):
    w, x, y, z = quaternion
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


def make_splats():
    names = ["x", "y", "z", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    names += ["f_dc_0", "f_dc_1", "f_dc_2", "opacity"]
    data = np.zeros(2, dtype=[(name, "<f4") for name in names])
    data["x"] = [1, 2]
    data["scale_0"] = -3
    data["rot_0"], data["rot_1"] = [1, 0.6], [0, 0.8]
    data["f_dc_1"] = 0.5
    return Splats(data)


def test_quaternions_round_trip_through_matrices():
    for matrix in (np.eye(3), TURN, TURN @ TURN.T, -np.diag([1.0, -1.0, 1.0]) * -1 @ TURN):
        if np.linalg.det(matrix) > 0:
            np.testing.assert_allclose(
                quaternion_to_matrix(matrix_to_quaternion(matrix)), matrix, atol=1e-6
            )


def test_quaternion_product_matches_matrix_product():
    second = np.array([0.6, 0.8, 0, 0])
    product = multiply_quaternions(matrix_to_quaternion(TURN), second[None])[0]
    np.testing.assert_allclose(
        quaternion_to_matrix(product), TURN @ quaternion_to_matrix(second), atol=1e-6
    )


def test_transform_moves_scales_and_turns_splats_and_keeps_color():
    splats = make_splats()
    shift = np.array([1.0, 2.0, 3.0])
    moved = transform_splats(splats, 2.0, TURN, shift)
    np.testing.assert_allclose(moved.positions, 2.0 * splats.positions @ TURN.T + shift, atol=1e-5)
    np.testing.assert_allclose(moved.scales[:, 0], splats.scales[:, 0] * 2, rtol=1e-5)
    np.testing.assert_allclose(
        quaternion_to_matrix(moved.quaternions[1]),
        TURN @ quaternion_to_matrix(splats.quaternions[1]),
        atol=1e-5,
    )
    np.testing.assert_array_equal(moved.data["f_dc_1"], splats.data["f_dc_1"])
    assert splats.data["x"][0] == 1  # The input isn't changed.
