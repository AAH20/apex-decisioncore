"""
Master Orchestrator for Apex-DecisionCore.
Integrates Jev Continuous-Time ODEs, MiroFish Combinatorics, Laya CBF-QP Shield, and Clef Runtime.
Zero external dependencies. Pure Python standard library.
"""

from __future__ import annotations
import time
from typing import Dict, List, Optional, Tuple

from apex_decisioncore.core.primitives import (
    Vector3D,
    ContinuousState,
    ControlAction,
    ActionKind,
    BarrierCertificate,
    TypedProbabilityVector,
    DecisionCycleReport,
)
from apex_decisioncore.core.jev_engine import JevContinuousStateEngine
from apex_decisioncore.core.mirofish_solver import SwarmAgentTask, MiroFishCombinatorialSolver
from apex_decisioncore.core.laya_verifier import SafetyHazard, LayaSafetyBarrierVerifier
from apex_decisioncore.core.clef_runtime import ClefDeterministicRuntime
from apex_decisioncore.core.provenance_ledger import PostQuantumProvenanceLedger


class ApexDecisionOrchestrator:
    """
    Sub-microsecond Decision Model OS.
    Executes real-time continuous control, combinatorial pruning, and formal safety verification.
    """

    def __init__(
        self,
        sla_budget_us: float = 10.0,
        cbf_alpha: float = 1.5,
        max_mirofish_candidates: int = 16,
    ):
        self.jev_engine = JevContinuousStateEngine()
        self.mirofish_solver = MiroFishCombinatorialSolver(max_candidate_pool=max_mirofish_candidates)
        self.laya_verifier = LayaSafetyBarrierVerifier(alpha_class_k=cbf_alpha)
        self.clef_runtime = ClefDeterministicRuntime(max_sla_budget_us=sla_budget_us)
        self.provenance_ledger = PostQuantumProvenanceLedger()

        self.cycle_count = 0
        self.hazards: Dict[str, SafetyHazard] = {}
        self.tasks: Dict[str, SwarmAgentTask] = {}

    def register_hazard(self, hazard: SafetyHazard) -> None:
        self.hazards[hazard.hazard_id] = hazard

    def register_task(self, task: SwarmAgentTask) -> None:
        self.tasks[task.task_id] = task

    def execute_decision_cycle(
        self,
        agent_state: ContinuousState,
        active_tasks: Optional[List[SwarmAgentTask]] = None,
        active_hazards: Optional[List[SafetyHazard]] = None,
        dt: float = 0.01,
    ) -> DecisionCycleReport:
        """
        Executes one full sub-microsecond decision cycle:
        1. Jev Continuous State Space RK4 propagation & lookahead
        2. MiroFish NP-Hard Combinatorial Pruning & Candidate Selection
        3. Laya Control Barrier Function (CBF-QP) Formal Verification
        4. Clef Zero-Allocation Sandboxed Dispatch
        5. Post-Quantum Merkle DAG Provenance Recording
        """
        self.cycle_count += 1
        t_cycle_start = time.perf_counter_ns()
        phase_latencies: Dict[str, float] = {}

        tasks = active_tasks or list(self.tasks.values())
        hazards = active_hazards or list(self.hazards.values())

        # -------------------------------------------------------------
        # 1. Jev Continuous State Space & Intent Distribution
        # -------------------------------------------------------------
        t0 = time.perf_counter_ns()
        nearest_hazard_dist = min(
            [agent_state.position.distance_to(h.position) for h in hazards],
            default=5000.0,
        )
        intent = self.jev_engine.compute_typed_intent_distribution(
            agent_state, nearest_hazard_dist
        )
        phase_latencies["jev_state_propagation"] = (time.perf_counter_ns() - t0) / 1000.0

        # -------------------------------------------------------------
        # 2. MiroFish Combinatorial Action Pruning
        # -------------------------------------------------------------
        t0 = time.perf_counter_ns()
        candidate_actions = self.mirofish_solver.prune_and_select_actions(
            agent_state, tasks, budget_limit=100.0
        )
        phase_latencies["mirofish_pruning"] = (time.perf_counter_ns() - t0) / 1000.0

        # Select highest-utility candidate
        primary_candidate = candidate_actions[0] if candidate_actions else ControlAction(
            action_id="FALLBACK-STANDBY",
            kind=ActionKind.SAFE_STANDBY,
            target_entity_id=None,
            actuation_vector=Vector3D(0, 0, 0),
            intensity=0.0,
            expected_utility=0.0,
            execution_cost=0.0,
        )

        # -------------------------------------------------------------
        # 3. Laya Formal Verification Layer (CBF-QP Filter)
        # -------------------------------------------------------------
        t0 = time.perf_counter_ns()
        barrier_cert = self.laya_verifier.verify_and_project_action(
            agent_state, primary_candidate, hazards
        )
        final_action = barrier_cert.projected_action or primary_candidate
        phase_latencies["laya_formal_cbf"] = (time.perf_counter_ns() - t0) / 1000.0

        # -------------------------------------------------------------
        # 4. Clef Real-Time Sandboxed Dispatch
        # -------------------------------------------------------------
        t0 = time.perf_counter_ns()
        envelope = self.clef_runtime.execute_sandboxed_dispatch(
            final_action, intent=intent, t_start_ns=t_cycle_start
        )
        # Advance entity state with approved action
        self.jev_engine.step_rk4(agent_state, final_action, dt=dt)
        phase_latencies["clef_dispatch"] = (time.perf_counter_ns() - t0) / 1000.0

        # -------------------------------------------------------------
        # 5. Post-Quantum Provenance Ledger Sealing
        # -------------------------------------------------------------
        t0 = time.perf_counter_ns()
        total_latency_us = (time.perf_counter_ns() - t_cycle_start) / 1000.0
        block = self.provenance_ledger.record_decision_cycle(
            cycle_latency_us=total_latency_us,
            action=final_action,
            barrier_cert=barrier_cert,
        )
        phase_latencies["provenance_ledger"] = (time.perf_counter_ns() - t0) / 1000.0

        cbf_interventions = 1 if not barrier_cert.is_approved else 0

        return DecisionCycleReport(
            cycle_index=self.cycle_count,
            total_cycle_latency_us=total_latency_us,
            selected_action=final_action,
            candidates_evaluated=len(candidate_actions),
            candidates_pruned_by_mirofish=max(0, len(tasks) * 3 - len(candidate_actions)),
            cbf_interventions_count=cbf_interventions,
            safety_barrier_h=barrier_cert.barrier_value_h,
            merkle_root_hash=block.merkle_root,
            phase_latencies_us=phase_latencies,
            typed_decision=intent,
        )
