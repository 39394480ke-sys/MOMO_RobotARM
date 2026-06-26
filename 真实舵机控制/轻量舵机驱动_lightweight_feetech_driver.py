"""轻量 Feetech SDK 驱动。

只依赖 feetech-servo-sdk 暴露的 scservo_sdk，不导入 lerobot/torch。
这个模块只做 raw 寄存器读写；角度映射、标定和安全检查仍由 RealArmController 负责。
"""

from __future__ import annotations

from typing import Any

from 标定工具_calibration_utils import ARM_MOTOR_IDS


CONTROL_TABLE: dict[str, tuple[int, int]] = {
    "ID": (5, 1),
    "Torque_Enable": (40, 1),
    "Goal_Position": (42, 2),
    "Present_Position": (56, 2),
    "Present_Velocity": (58, 2),
    "Present_Load": (60, 2),
    "Present_Voltage": (62, 1),
    "Present_Temperature": (63, 1),
    "Status": (65, 1),
    "Moving": (66, 1),
    "Present_Current": (69, 2),
}

SIGN_MAGNITUDE_BITS = {
    "Goal_Position": 15,
    "Present_Position": 15,
    "Present_Velocity": 15,
    "Present_Load": 10,
}

DEFAULT_BAUDRATE = 1_000_000
EXPECTED_STS3215_MODEL = 777


def encode_sign_magnitude(value: int, sign_bit_index: int) -> int:
    max_magnitude = (1 << sign_bit_index) - 1
    magnitude = abs(int(value))
    if magnitude > max_magnitude:
        raise ValueError(f"raw magnitude {magnitude} exceeds {max_magnitude}")
    return ((1 if value < 0 else 0) << sign_bit_index) | magnitude


def decode_sign_magnitude(encoded_value: int, sign_bit_index: int) -> int:
    direction_bit = (int(encoded_value) >> sign_bit_index) & 1
    magnitude_mask = (1 << sign_bit_index) - 1
    magnitude = int(encoded_value) & magnitude_mask
    return -magnitude if direction_bit else magnitude


class LightweightFeetechBus:
    """STS/SMS 系列 raw 总线封装。"""

    def __init__(self, port: str, motor_ids_by_joint: dict[str, int], baudrate: int = DEFAULT_BAUDRATE):
        self.port = port
        self.motor_ids_by_joint = dict(motor_ids_by_joint)
        self.baudrate = int(baudrate)
        self.scs: Any | None = None
        self.port_handler: Any | None = None
        self.packet_handler: Any | None = None
        self.connected = False

    def connect(self) -> dict[int, int]:
        import scservo_sdk as scs

        self.scs = scs
        self.port_handler = scs.PortHandler(self.port)
        if not self.port_handler.setBaudRate(self.baudrate):
            raise RuntimeError(f"无法打开串口 {self.port}，或不支持 baudrate={self.baudrate}。")
        self.packet_handler = scs.PacketHandler(0)
        self.connected = True
        return self.ping_expected()

    def disconnect(self) -> None:
        if self.port_handler is not None and getattr(self.port_handler, "is_open", False):
            self.port_handler.closePort()
        self.connected = False

    def ping_expected(self) -> dict[int, int]:
        self._ensure_connected()
        found: dict[int, int] = {}
        for motor_id in self.motor_ids_by_joint.values():
            model, result, error = self.packet_handler.ping(self.port_handler, int(motor_id))
            if self._comm_ok(result, error):
                found[int(motor_id)] = int(model)
        return found

    def read(self, register_name: str, joint_key: str) -> int:
        motor_id = self._motor_id(joint_key)
        raw_value = self._read_by_id(register_name, motor_id)
        return self._decode(register_name, raw_value)

    def read_many(self, register_name: str, joint_keys: list[str]) -> dict[str, int]:
        return {joint_key: self.read(register_name, joint_key) for joint_key in joint_keys}

    def write(self, register_name: str, joint_key: str, value: int) -> None:
        motor_id = self._motor_id(joint_key)
        self._write_by_id(register_name, motor_id, self._encode(register_name, int(value)))

    def write_many(self, register_name: str, values_by_joint: dict[str, int]) -> None:
        for joint_key, value in values_by_joint.items():
            self.write(register_name, joint_key, int(value))

    def _read_by_id(self, register_name: str, motor_id: int) -> int:
        address, size = self._register(register_name)
        if size == 1:
            value, result, error = self.packet_handler.read1ByteTxRx(self.port_handler, motor_id, address)
        elif size == 2:
            value, result, error = self.packet_handler.read2ByteTxRx(self.port_handler, motor_id, address)
        elif size == 4:
            value, result, error = self.packet_handler.read4ByteTxRx(self.port_handler, motor_id, address)
        else:
            raise ValueError(f"不支持的寄存器长度：{register_name} size={size}")
        self._raise_if_comm_failed(result, error, f"读取 {register_name} ID {motor_id}")
        return int(value)

    def _write_by_id(self, register_name: str, motor_id: int, value: int) -> None:
        address, size = self._register(register_name)
        if size == 1:
            result, error = self.packet_handler.write1ByteTxRx(self.port_handler, motor_id, address, int(value))
        elif size == 2:
            result, error = self.packet_handler.write2ByteTxRx(self.port_handler, motor_id, address, int(value))
        elif size == 4:
            result, error = self.packet_handler.write4ByteTxRx(self.port_handler, motor_id, address, int(value))
        else:
            raise ValueError(f"不支持的寄存器长度：{register_name} size={size}")
        self._raise_if_comm_failed(result, error, f"写入 {register_name} ID {motor_id}")

    def _motor_id(self, joint_key: str) -> int:
        if joint_key not in self.motor_ids_by_joint:
            raise KeyError(f"未知舵机：{joint_key}")
        return int(self.motor_ids_by_joint[joint_key])

    @staticmethod
    def _register(register_name: str) -> tuple[int, int]:
        if register_name not in CONTROL_TABLE:
            raise KeyError(f"轻量 SDK 后端暂不支持寄存器：{register_name}")
        return CONTROL_TABLE[register_name]

    @staticmethod
    def _encode(register_name: str, value: int) -> int:
        if register_name in SIGN_MAGNITUDE_BITS:
            return encode_sign_magnitude(value, SIGN_MAGNITUDE_BITS[register_name])
        return int(value)

    @staticmethod
    def _decode(register_name: str, value: int) -> int:
        if register_name in SIGN_MAGNITUDE_BITS:
            return decode_sign_magnitude(value, SIGN_MAGNITUDE_BITS[register_name])
        return int(value)

    def _ensure_connected(self) -> None:
        if not self.connected or self.port_handler is None or self.packet_handler is None:
            raise RuntimeError("轻量 Feetech 总线尚未连接。")

    def _comm_ok(self, result: int, error: int) -> bool:
        return self.scs is not None and result == self.scs.COMM_SUCCESS and int(error) == 0

    def _raise_if_comm_failed(self, result: int, error: int, action: str) -> None:
        if self._comm_ok(result, error):
            return
        result_msg = self.packet_handler.getTxRxResult(result)
        error_msg = self.packet_handler.getRxPacketError(error) if error else ""
        detail = " ".join(part for part in [result_msg, error_msg] if part)
        raise RuntimeError(f"{action} 失败：{detail or f'result={result} error={error}'}")


def build_motor_ids(config: dict[str, Any], calibration_data: dict[str, Any], joint_keys: list[str]) -> dict[str, int]:
    ids: dict[str, int] = {}
    for joint_key in joint_keys:
        entry = calibration_data.get(joint_key, {})
        if "id" in entry:
            ids[joint_key] = int(entry["id"])
            continue
        if joint_key in ARM_MOTOR_IDS:
            ids[joint_key] = int(ARM_MOTOR_IDS[joint_key])
            continue
        for joint in config.get("robot", {}).get("joints", []):
            if joint.get("key") == joint_key:
                ids[joint_key] = int(joint["舵机ID"])
                break
    return ids
