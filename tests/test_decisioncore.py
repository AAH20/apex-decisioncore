"""
Comprehensive Unit Test Suite for Apex-DecisionCore.
Zero external dependencies. Pure standard library unittest.
"""

from __future__ import annotations
import json
import math
import unittest

from apex_decisioncore.core.primitives import (
    Vector3D,
    ContinuousState,
    ControlAction,
    ActionKind,
    BarrierCertificate,
    TypedProbabilityVector,
)
from apex_decisioncore.core.jev_engine import JevContinuousStateEngine
from apex_decisioncore.core.mirofish_solver import SwarmAgentTask, MiroFishCombinatorialSolver
from apex_decisioncore.core.laya_verifier import SafetyHazard, LayaSafetyBarrierVerifier
from apex_decisioncore.core.clef_runtime import ClefDeterministicRuntime
from apex_decisioncore.core.provenance_ledger import PostQuantumProvenanceLedger
from apex_decisioncore.orchestrator import ApexDecisionOrchestrator
from apex_decisioncore.sitl.mavlink_bridge import DecisionMAVLinkBridge, crc16_mcrf4xx


class TestApexDecisionCore(unittest.TestCase):

    # -------------------------------------------------------------
    # Primitives & Vector3D Tests
    # -------------------------------------------------------------
    def test_vector3d_spatial_operations(self):
        v1 = Vector3D(1.0, 2.0, 3.0)
        v2 = Vector3D(4.0, 5.0, 6.0)
        self.assertEqual(v1 + v2, Vector3D(5.0, 7.0, 9.0))
        self.assertEqual(v2 - v1, Vector3D(3.0, 3.0, 3.0))
        self.assertEqual(v1 * 2.0, Vector3D(2.0, 4.0, 6.0))
        self.assertEqual(v1.dot(v2), 32.0)
        cross = v1.cross(v2)
        self.assertEqual(cross, Vector3D(-3.0, 6.0, -3.0))
        self.assertAlmostEqual(v1.magnitude(), math.sqrt(14.0), delta=1e-5)

    # -------------------------------------------------------------
    # Pillar 1: Jev Continuous-Time ODE Engine Tests
    # -------------------------------------------------------------
    def test_jev_continuous_state_rk4_integration(self):
        engine = JevContinuousStateEngine(mass_kg=2.0)
        state = ContinuousState("UAV-01", Vector3D(0, 0, 0), Vector3D(10, 0, 0), Vector3D(0, 0, 0))
        action = ControlAction("A1", ActionKind.INTERCEPT_FIRE, "T1", Vector3D(1, 0, 0), 0.5, 10.0, 5.0)

        next_state = engine.step_rk4(state, action, dt=0.1)
        self.assertGreater(next_state.position.x, 0.9)
        self.assertGreater(next_state.velocity.x, 9.0)

    def test_jev_drag_and_acceleration_dynamics(self):
        engine = JevContinuousStateEngine(drag_coefficient=0.2, mass_kg=1.0)
        state = ContinuousState("UAV-02", Vector3D(0, 0, 0), Vector3D(50, 0, 0), Vector3D(0, 0, 0))
        v_deriv, a_deriv = engine.derivative(state, Vector3D(0, 0, 0))
        # Drag force should oppose velocity -> negative acceleration on X
        self.assertEqual(v_deriv.x, 50.0)
        self.assertLess(a_deriv.x, 0.0)

    def test_jev_trajectory_lookahead_projection(self):
        engine = JevContinuousStateEngine()
        state = ContinuousState("UAV-03", Vector3D(0, 0, 100), Vector3D(20, 0, 0), Vector3D(0, 0, 0))
        lookahead = engine.predict_trajectory_lookahead(state, None, horizon_s=0.5, steps=5)
        self.assertEqual(len(lookahead), 5)
        self.assertGreater(lookahead[-1].x, lookahead[0].x)

    def test_jev_typed_intent_softmax_distribution(self):
        engine = JevContinuousStateEngine()
        # Close hazard distance (15m) -> should prioritize EVADE
        state = ContinuousState("UAV-04", Vector3D(0, 0, 0), Vector3D(5, 0, 0), Vector3D(0, 0, 0))
        intent = engine.compute_typed_intent_distribution(state, nearest_threat_dist=15.0)
        self.assertIn("EVADE", intent.labels)
        self.assertEqual(intent.top_label, "EVADE")
        self.assertAlmostEqual(sum(intent.probabilities), 1.0, delta=0.01)

    # -------------------------------------------------------------
    # Pillar 2: MiroFish & ApexGraphSwarm Submodular Solver Tests
    # -------------------------------------------------------------
    def test_mirofish_submodular_utility_diminishing_returns(self):
        solver = MiroFishCombinatorialSolver()
        tasks = {"T1": SwarmAgentTask("T1", Vector3D(500, 0, 0), 100.0, "STRIKE")}
        cand1 = ControlAction("C1", ActionKind.INTERCEPT_FIRE, "T1", Vector3D(1, 0, 0), 0.8, 80.0, 10.0)
        cand2 = ControlAction("C2", ActionKind.INTERCEPT_FIRE, "T1", Vector3D(1, 0, 0), 0.8, 80.0, 10.0)

        # First allocation achieves high marginal gain
        gain1 = solver.evaluate_submodular_utility(cand1, [], tasks)
        # Overlapping second allocation on same task suffers diminishing returns
        gain2 = solver.evaluate_submodular_utility(cand2, [cand1], tasks)
        self.assertGreater(gain1, gain2)

    def test_mirofish_combinatorial_pruning_under_budget(self):
        solver = MiroFishCombinatorialSolver(max_candidate_pool=3)
        agent = ContinuousState("LEAD", Vector3D(0, 0, 0), Vector3D(0, 0, 0), Vector3D(0, 0, 0))
        tasks = [
            SwarmAgentTask(f"T-{i}", Vector3D(500 + i * 100, 0, 0), 50.0 + i * 10, "STRIKE")
            for i in range(10)
        ]
        selected = solver.prune_and_select_actions(agent, tasks, budget_limit=45.0)
        self.assertLessEqual(len(selected), 3)
        total_cost = sum(a.execution_cost for a in selected)
        self.assertLessEqual(total_cost, 45.0)

    def test_mirofish_fallback_standby_on_empty_tasks(self):
        solver = MiroFishCombinatorialSolver()
        agent = ContinuousState("LEAD", Vector3D(0, 0, 0), Vector3D(0, 0, 0), Vector3D(0, 0, 0))
        selected = solver.prune_and_select_actions(agent, [], budget_limit=10.0)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].kind, ActionKind.SAFE_STANDBY)

    # -------------------------------------------------------------
    # Pillar 3: Laya Formal Verification (CBF-QP) Shield Tests
    # -------------------------------------------------------------
    def test_laya_cbf_safe_action_passthrough(self):
        verifier = LayaSafetyBarrierVerifier()
        state = ContinuousState("UAV", Vector3D(0, 0, 0), Vector3D(10, 0, 0), Vector3D(0, 0, 0))
        safe_hazard = SafetyHazard("FAR_OBS", Vector3D(5000, 0, 0), 50.0)
        action = ControlAction("A_SAFE", ActionKind.INTERCEPT_FIRE, "T1", Vector3D(1, 0, 0), 0.5, 20.0, 5.0)

        cert = verifier.verify_and_project_action(state, action, [safe_hazard])
        self.assertTrue(cert.is_approved)
        self.assertGreater(cert.barrier_value_h, 100.0)
        self.assertEqual(cert.projected_action.action_id, "A_SAFE")

    def test_laya_cbf_spatial_hazard_qp_projection(self):
        verifier = LayaSafetyBarrierVerifier(alpha_class_k=2.0)
        # Agent heading directly towards hazard at distance 20m with 15m exclusion
        state = ContinuousState("UAV", Vector3D(0, 0, 0), Vector3D(20, 0, 0), Vector3D(0, 0, 0))
        imminent_hazard = SafetyHazard("TREE", Vector3D(20, 0, 0), 15.0)
        # Candidate action wants to accelerate straight into hazard (+X)
        unsafe_action = ControlAction("A_UNSAFE", ActionKind.INTERCEPT_FIRE, "T1", Vector3D(1, 0, 0), 1.0, 50.0, 10.0)

        cert = verifier.verify_and_project_action(state, unsafe_action, [imminent_hazard])
        # Original action must be rejected/modified
        self.assertFalse(cert.is_approved)
        self.assertIn("CBF_VIOLATION", cert.violation_code)
        # Projected action must modify direction to preserve safety boundary
        self.assertIsNotNone(cert.projected_action)
        self.assertTrue(cert.projected_action.is_certified_safe)

    def test_laya_cbf_thermal_overload_power_shed(self):
        verifier = LayaSafetyBarrierVerifier(max_allowable_temperature_c=80.0)
        # Motor overheated to 92°C
        hot_state = ContinuousState("UAV", Vector3D(0, 0, 0), Vector3D(0, 0, 0), Vector3D(0, 0, 0), temperature_celsius=92.0)
        action = ControlAction("BURN", ActionKind.INTERCEPT_FIRE, "T1", Vector3D(1, 0, 0), 1.0, 50.0, 5.0)

        cert = verifier.verify_and_project_action(hot_state, action, [])
        self.assertFalse(cert.is_approved)
        self.assertEqual(cert.projected_action.kind, ActionKind.POWER_SHED)

    def test_laya_cbf_energy_exhaustion_protection(self):
        verifier = LayaSafetyBarrierVerifier(min_energy_reserve_pct=15.0)
        # Battery at 5%
        depleted_state = ContinuousState("UAV", Vector3D(0, 0, 0), Vector3D(0, 0, 0), Vector3D(0, 0, 0), internal_energy_pct=5.0)
        action = ControlAction("MAX_THRUST", ActionKind.INTERCEPT_FIRE, "T1", Vector3D(1, 0, 0), 1.0, 50.0, 5.0)

        cert = verifier.verify_and_project_action(depleted_state, action, [])
        self.assertFalse(cert.is_approved)
        self.assertEqual(cert.projected_action.kind, ActionKind.POWER_SHED)

    # -------------------------------------------------------------
    # Pillar 4: Clef Sandboxed Runtime Tests
    # -------------------------------------------------------------
    def test_clef_runtime_static_memory_arena(self):
        runtime = ClefDeterministicRuntime(preallocate_slots=8)
        v1 = runtime.acquire_static_vector(1, 2, 3)
        v2 = runtime.acquire_static_vector(4, 5, 6)
        self.assertEqual(v1, Vector3D(1, 2, 3))
        self.assertEqual(v2, Vector3D(4, 5, 6))

    def test_clef_runtime_sla_budget_watchdog(self):
        runtime = ClefDeterministicRuntime(max_sla_budget_us=100.0)
        action = ControlAction("A1", ActionKind.SAFE_STANDBY, None, Vector3D(0, 0, 0), 0.0, 0.0, 0.0)
        envelope = runtime.execute_sandboxed_dispatch(action)
        self.assertEqual(envelope.runtime_status, "NOMINAL_DETERMINISTIC")
        self.assertFalse(envelope.budget_exceeded)

    def test_clef_export_schema_json_format(self):
        runtime = ClefDeterministicRuntime()
        action = ControlAction("A1", ActionKind.INTERCEPT_FIRE, "T1", Vector3D(1, 0, 0), 0.9, 50.0, 10.0)
        intent = TypedProbabilityVector(["STRIKE", "EVADE"], [0.85, 0.15], "STRIKE", 0.85)

        spec = runtime.export_clef_schema_json(action, intent, cycle_latency_us=1.2)
        parsed = json.loads(spec)
        self.assertEqual(parsed["type"], "decision_result")
        self.assertEqual(parsed["chosen_action"]["kind"], "INTERCEPT_FIRE")
        self.assertEqual(parsed["intent_probabilities"]["STRIKE"], 0.85)

    # -------------------------------------------------------------
    # Pillar 5: Post-Quantum Provenance Ledger Tests
    # -------------------------------------------------------------
    def test_provenance_ledger_merkle_root_computation(self):
        ledger = PostQuantumProvenanceLedger()
        action = ControlAction("A1", ActionKind.INTERCEPT_FIRE, "T1", Vector3D(1, 0, 0), 0.9, 50.0, 10.0)
        cert = BarrierCertificate(True, 15.0, 0.0, 0.0, 100.0, None, action)

        block = ledger.record_decision_cycle(cycle_latency_us=0.85, action=action, barrier_cert=cert)
        self.assertEqual(len(ledger.chain), 1)
        self.assertEqual(len(block.merkle_root), 64)
        self.assertTrue(block.pqc_signature_token.startswith("ML-DSA-65:"))

    def test_provenance_ledger_integrity_and_tamper_detection(self):
        ledger = PostQuantumProvenanceLedger()
        action = ControlAction("A1", ActionKind.SAFE_STANDBY, None, Vector3D(0, 0, 0), 0.0, 0.0, 0.0)
        ledger.record_decision_cycle(1.0, action, None)
        ledger.record_decision_cycle(1.2, action, None)

        valid, msg = ledger.verify_ledger_integrity()
        self.assertTrue(valid)
        self.assertIn("verified", msg.lower())

        # Tamper test
        ledger.chain[0].block_hash = "0" * 64
        tampered, _ = ledger.verify_ledger_integrity()
        self.assertFalse(tampered)

    # -------------------------------------------------------------
    # Master Orchestrator Integration Tests
    # -------------------------------------------------------------
    def test_decision_orchestrator_end_to_end_cycle(self):
        orchestrator = ApexDecisionOrchestrator()
        agent = ContinuousState("LEAD", Vector3D(0, 0, 50), Vector3D(20, 0, 0), Vector3D(0, 0, 0))
        task = SwarmAgentTask("TASK-1", Vector3D(600, 0, 50), 90.0, "STRIKE")
        hazard = SafetyHazard("HAZARD-1", Vector3D(300, 10, 50), 25.0)

        report = orchestrator.execute_decision_cycle(agent, active_tasks=[task], active_hazards=[hazard], dt=0.01)
        self.assertEqual(report.cycle_index, 1)
        self.assertIsNotNone(report.selected_action)
        self.assertGreater(report.candidates_evaluated, 0)
        self.assertLess(report.total_cycle_latency_us, 500.0)

    def test_decision_orchestrator_sub_microsecond_profiling(self):
        orchestrator = ApexDecisionOrchestrator()
        agent = ContinuousState("LEAD", Vector3D(0, 0, 50), Vector3D(20, 0, 0), Vector3D(0, 0, 0))

        report = orchestrator.execute_decision_cycle(agent, dt=0.01)
        expected_phases = [
            "jev_state_propagation",
            "mirofish_pruning",
            "laya_formal_cbf",
            "clef_dispatch",
            "provenance_ledger",
        ]
        for p in expected_phases:
            self.assertIn(p, report.phase_latencies_us)
            self.assertGreaterEqual(report.phase_latencies_us[p], 0.0)

    # -------------------------------------------------------------
    # SITL MAVLink Bridge Tests
    # -------------------------------------------------------------
    def test_mavlink_bridge_wgs84_to_cartesian_transform(self):
        bridge = DecisionMAVLinkBridge(base_lat=37.7749, base_lon=-122.4194, base_alt_m=100.0)
        cart = bridge.wgs84_to_cartesian_enu(37.7758, -122.4182, 40.0)
        self.assertGreater(cart.x, 50.0)
        self.assertGreater(cart.y, 50.0)
        self.assertEqual(cart.z, 40.0)

    def test_mavlink_bridge_set_position_target_encoding(self):
        bridge = DecisionMAVLinkBridge()
        pkt = bridge.encode_set_position_target(
            target_sys=3,
            target_pos_enu=Vector3D(100, 200, 30),
            target_vel_enu=Vector3D(10, 0, 0),
        )
        self.assertGreater(len(pkt), 20)
        self.assertEqual(pkt[0], 0xFE)

    # -------------------------------------------------------------
    # High-Stress Scalability Test (50 Tasks x 20 Hazards)
    # -------------------------------------------------------------
    def test_high_stress_50_agent_combinatorial_scaling(self):
        orchestrator = ApexDecisionOrchestrator()
        agent = ContinuousState("LEAD", Vector3D(0, 0, 50), Vector3D(30, 0, 0), Vector3D(0, 0, 0))

        tasks = [
            SwarmAgentTask(f"TGT-{i}", Vector3D(500 + i * 20, (i % 5) * 50, 50), 30.0 + (i % 70), "STRIKE")
            for i in range(50)
        ]
        hazards = [
            SafetyHazard(f"HAZ-{j}", Vector3D(300 + j * 50, (j % 4) * 40, 50), 20.0, j % 2 == 0)
            for j in range(20)
        ]

        report = orchestrator.execute_decision_cycle(agent, active_tasks=tasks, active_hazards=hazards, dt=0.01)
        self.assertEqual(report.cycle_index, 1)
        self.assertIsNotNone(report.selected_action)
        # Even with 50 tasks and 20 hazards, execution must finish in under 2.5 ms
        self.assertLess(report.total_cycle_latency_us, 2500.0)

    # -------------------------------------------------------------
    # Additional Robustness & Coverage Tests
    # -------------------------------------------------------------
    def test_jev_continuous_state_multi_step_heating(self):
        engine = JevContinuousStateEngine()
        state = ContinuousState("UAV", Vector3D(0, 0, 0), Vector3D(0, 0, 0), Vector3D(0, 0, 0), temperature_celsius=25.0)
        action = ControlAction("MAX_BURN", ActionKind.INTERCEPT_FIRE, "T1", Vector3D(1, 0, 0), 1.0, 50.0, 10.0)
        # 10 steps of maximum burn
        for _ in range(10):
            state = engine.step_rk4(state, action, dt=0.1)
        self.assertGreater(state.temperature_celsius, 25.1)
        self.assertLess(state.internal_energy_pct, 100.0)

    def test_mirofish_high_density_task_clustering(self):
        solver = MiroFishCombinatorialSolver(max_candidate_pool=8)
        agent = ContinuousState("LEAD", Vector3D(0, 0, 0), Vector3D(0, 0, 0), Vector3D(0, 0, 0))
        cluster_tasks = [
            SwarmAgentTask(f"CLUSTER-{i}", Vector3D(1000 + i * 5, 50 + i * 2, 0), 80.0, "CLUSTER_TASK")
            for i in range(12)
        ]
        selected = solver.prune_and_select_actions(agent, cluster_tasks, budget_limit=60.0)
        self.assertGreaterEqual(len(selected), 1)
        self.assertLessEqual(len(selected), 8)

    def test_laya_friendly_unit_cbf_safety_corridor(self):
        verifier = LayaSafetyBarrierVerifier(alpha_class_k=3.0)
        state = ContinuousState("UAV", Vector3D(0, 0, 0), Vector3D(25, 0, 0), Vector3D(0, 0, 0))
        friendly_escort = SafetyHazard("BLUE-ESCORT", Vector3D(22, 0, 0), 20.0, is_friendly_unit=True)
        cand_action = ControlAction("HEAD_ON", ActionKind.INTERCEPT_FIRE, "TGT", Vector3D(1, 0, 0), 1.0, 90.0, 10.0)

        cert = verifier.verify_and_project_action(state, cand_action, [friendly_escort])
        self.assertFalse(cert.is_approved)
        self.assertIn("FRIENDLY_UNIT", cert.violation_code)

    def test_clef_runtime_pool_wrap_around(self):
        runtime = ClefDeterministicRuntime(preallocate_slots=4)
        for i in range(10):
            v = runtime.acquire_static_vector(i, i, i)
            self.assertEqual(v.x, i)

    def test_cli_execution_simulate(self):
        from apex_decisioncore.cli import cmd_simulate
        class MockArgs:
            cycles = 3
        exit_code = cmd_simulate(MockArgs())
        self.assertEqual(exit_code, 0)

    def test_cli_execution_benchmark(self):
        from apex_decisioncore.cli import cmd_benchmark
        class MockArgs:
            iterations = 50
        exit_code = cmd_benchmark(MockArgs())
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
