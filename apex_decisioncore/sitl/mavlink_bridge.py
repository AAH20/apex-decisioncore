"""
SITL MAVLink Bridge for ArduPilot & PX4 on Gazebo.
Translates MAVLink telemetry to ContinuousState and streams verified u* commands to vehicles.
Zero external dependencies. Pure Python standard library.
"""

from __future__ import annotations
import math
import socket
import struct
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from apex_decisioncore.core.primitives import Vector3D, ContinuousState, ControlAction


def crc16_mcrf4xx(data: bytes, initial: int = 0xFFFF) -> int:
    crc = initial
    for byte in data:
        tmp = byte ^ (crc & 0xFF)
        tmp = (tmp ^ (tmp << 4)) & 0xFF
        crc = (crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)
    return crc & 0xFFFF


MAVLINK_CRC_EXTRA = {
    0: 50,    # HEARTBEAT
    30: 39,   # ATTITUDE
    33: 104,  # GLOBAL_POSITION_INT
    76: 152,  # COMMAND_LONG
    84: 143,  # SET_POSITION_TARGET_LOCAL_NED
}


class DecisionMAVLinkBridge:
    """
    Connects Apex-DecisionCore to ArduPilot / PX4 SITL instances running in Gazebo.
    """

    def __init__(
        self,
        base_lat: float = 37.7749,
        base_lon: float = -122.4194,
        base_alt_m: float = 100.0,
    ):
        self.origin_lat = base_lat
        self.origin_lon = base_lon
        self.origin_alt = base_alt_m
        self.seq = 0

    def wgs84_to_cartesian_enu(self, lat: float, lon: float, alt_rel: float) -> Vector3D:
        r_earth = 6378137.0
        d_lat_rad = math.radians(lat - self.origin_lat)
        d_lon_rad = math.radians(lon - self.origin_lon)
        lat_mid_rad = math.radians((lat + self.origin_lat) / 2.0)

        x_east = d_lon_rad * r_earth * math.cos(lat_mid_rad)
        y_north = d_lat_rad * r_earth
        z_up = alt_rel
        return Vector3D(x_east, y_north, z_up)

    def decode_global_position_int(self, data: bytes) -> Optional[ContinuousState]:
        """Decodes MAVLink v1/v2 packet into ContinuousState."""
        if len(data) < 8:
            return None

        magic = data[0]
        if magic == 0xFE:
            payload_len = data[1]
            sys_id = data[3]
            msg_id = data[5]
            payload = data[6 : 6 + payload_len]
        elif magic == 0xFD:
            payload_len = data[1]
            sys_id = data[5]
            msg_id = data[7] | (data[8] << 8) | (data[9] << 16)
            payload = data[10 : 10 + payload_len]
        else:
            return None

        if msg_id != 33 or len(payload) < 28:
            return None

        fields = struct.unpack("<IiiiihhhH", payload[:28])
        lat = fields[1] / 1e7
        lon = fields[2] / 1e7
        rel_alt = fields[4] / 1000.0
        vn = fields[5] / 100.0
        ve = fields[6] / 100.0
        vd = fields[7] / 100.0

        pos = self.wgs84_to_cartesian_enu(lat, lon, rel_alt)
        vel = Vector3D(ve, vn, -vd)  # ENU frame

        return ContinuousState(
            entity_id=f"UAV-{sys_id:03d}",
            position=pos,
            velocity=vel,
            acceleration=Vector3D(0, 0, 0),
            timestamp_ns=time.perf_counter_ns(),
        )

    def encode_set_position_target(
        self, target_sys: int, target_pos_enu: Vector3D, target_vel_enu: Vector3D
    ) -> bytes:
        """
        Encodes MAVLink SET_POSITION_TARGET_LOCAL_NED (msg #84) to steer physical vehicle in Gazebo.
        """
        # Coordinate map: North = y, East = x, Down = -z
        x_n = target_pos_enu.y
        y_e = target_pos_enu.x
        z_d = -target_pos_enu.z

        vx_n = target_vel_enu.y
        vy_e = target_vel_enu.x
        vz_d = -target_vel_enu.z

        # Mask: position + velocity enabled, acceleration ignored = 0b0000110111000000 = 0x0DC0
        type_mask = 0x0DC0
        coord_frame = 1  # MAV_FRAME_LOCAL_NED

        payload = struct.pack(
            "<IfffffffffffHBBB",
            int(time.time() * 1000) % 10000000,
            x_n, y_e, z_d,
            vx_n, vy_e, vz_d,
            0.0, 0.0, 0.0,  # afx, afy, afz
            0.0, 0.0,       # yaw, yaw_rate
            type_mask,
            target_sys,
            1,              # target_comp
            coord_frame,
        )

        msg_id = 84
        seq = self.seq & 0xFF
        self.seq = (self.seq + 1) & 0xFF
        header = struct.pack("<BBBBBB", 0xFE, len(payload), seq, 254, 1, msg_id)
        raw = header + payload

        crc = crc16_mcrf4xx(raw[1:])
        crc = crc16_mcrf4xx(bytes([MAVLINK_CRC_EXTRA[84]]), crc)
        return raw + struct.pack("<H", crc)
