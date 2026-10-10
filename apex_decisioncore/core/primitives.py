"""
Mathematical & Operational Primitives for Apex-DecisionCore.
Zero external dependencies. Pure Python standard library.
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Vector3D:
    x: float
    y: float
    z: float

    def __add__(self, other: Vector3D) -> Vector3D:
        return Vector3D(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: Vector3D) -> Vector3D:
        return Vector3D(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar: float) -> Vector3D:
        return Vector3D(self.x * scalar, self.y * scalar, self.z * scalar)

    def __rmul__(self, scalar: float) -> Vector3D:
        return self * scalar

    def magnitude(self) -> float:
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def dot(self, other: Vector3D) -> float:
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: Vector3D) -> Vector3D:
        return Vector3D(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    def distance_to(self, other: Vector3D) -> float:
        return (self - other).magnitude()

    def normalized(self) -> Vector3D:
        mag = self.magnitude()
        if mag < 1e-9:
            return Vector3D(0.0, 0.0, 0.0)
        return Vector3D(self.x / mag, self.y / mag, self.z / mag)


@dataclass
class ContinuousState:
    """Continuous-time dynamic state vector x(t) in physical space."""
    entity_id: str
    position: Vector3D
    velocity: Vector3D
    acceleration: Vector3D
    orientation_rad: float = 0.0
    internal_energy_pct: float = 100.0
    temperature_celsius: float = 25.0
    state_covariance_diag: Tuple[float, float, float] = (0.1, 0.1, 0.1)
    timestamp_ns: int = 0


class ActionKind(str, Enum):
    INTERCEPT_FIRE = "INTERCEPT_FIRE"
    KINEMATIC_EVADE = "KINEMATIC_EVADE"
    SENSOR_SLEW = "SENSOR_SLEW"
    POWER_SHED = "POWER_SHED"
    SWARM_JOIN = "SWARM_JOIN"
    SAFE_STANDBY = "SAFE_STANDBY"


@dataclass
class ControlAction:
    """Candidate or certified actuation command u(t)."""
    action_id: str
    kind: ActionKind
    target_entity_id: Optional[str]
    actuation_vector: Vector3D
    intensity: float  # Scale 0.0 to 1.0 (e.g. thrust or laser power)
    expected_utility: float  # Marginal gain
    execution_cost: float
    cbf_safety_margin: float = 1.0
    is_certified_safe: bool = True


@dataclass
class BarrierCertificate:
    """Mathematical safety guarantee proof under Control Barrier Function."""
    is_approved: bool
    barrier_value_h: float  # h(x) >= 0 is unconditionally safe
    drift_derivative: float
    control_derivative: float
    closest_hazard_distance_m: float
    violation_code: Optional[str] = None
    projected_action: Optional[ControlAction] = None


@dataclass
class TypedProbabilityVector:
    """Jev & Cloudflare Clef compatible typed category distribution."""
    labels: List[str]
    probabilities: List[float]
    top_label: str
    top_confidence: float

    def to_dict(self) -> Dict[str, float]:
        return {label: prob for label, prob in zip(self.labels, self.probabilities)}


@dataclass
class DecisionCycleReport:
    """Comprehensive performance and execution report for one microsecond cycle."""
    cycle_index: int
    total_cycle_latency_us: float
    selected_action: Optional[ControlAction]
    candidates_evaluated: int
    candidates_pruned_by_mirofish: int
    cbf_interventions_count: int
    safety_barrier_h: float
    merkle_root_hash: str
    phase_latencies_us: Dict[str, float] = field(default_factory=dict)
    typed_decision: Optional[TypedProbabilityVector] = None
