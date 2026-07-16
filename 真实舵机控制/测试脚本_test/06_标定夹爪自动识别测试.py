"""标定程序应在轻量 SDK 未发现 J16 时自动降级。"""

from __future__ import annotations

from unittest.mock import patch

import 真实测试路径_test_paths  # noqa: F401
import 标定程序_calibrate as calibration


class FakeBus:
    def __init__(self, found: dict[int, int]):
        self.found = found
        self.disconnected = False

    def connect(self) -> dict[int, int]:
        return self.found

    def disconnect(self) -> None:
        self.disconnected = True


def main() -> None:
    arm_found = {motor_id: 777 for motor_id in range(10, 16)}
    first_bus = FakeBus(arm_found)
    arm_only_bus = object()

    with (
        patch.object(calibration, "create_feetech_bus", return_value=first_bus),
        patch.object(calibration, "connect_feetech_bus", return_value=arm_only_bus) as reconnect,
    ):
        bus, include_gripper = calibration.connect_optional_gripper_bus(
            "/dev/momo-servo",
            include_gripper=True,
            backend="sdk",
            baudrate=1_000_000,
        )

    assert bus is arm_only_bus
    assert include_gripper is False
    assert first_bus.disconnected is True
    reconnect.assert_called_once_with(
        "/dev/momo-servo",
        include_gripper=False,
        backend="sdk",
        baudrate=1_000_000,
    )
    print("PASS: 轻量 SDK 未发现 ID16 时自动切换为无夹爪模式")


if __name__ == "__main__":
    main()
