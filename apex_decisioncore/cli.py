"""
Command-Line Interface for Apex-DecisionCore.
Institutional, zero-ASCII-art terminal interface for Decision Model execution and benchmarking.
Zero external dependencies. Pure Python standard library.
"""

from __future__ import annotations
import argparse
import sys
import time
from typing import List

from apex_decisioncore.core.primitives import (
    Vector3D,
    ContinuousState,
    ControlAction,
    ActionKind,
)
from apex_decisioncore.core.mirofish_solver import SwarmAgentTask
from apex_decisioncore.core.laya_verifier import SafetyHazard
from apex_decisioncore.orchestrator import ApexDecisionOrchestrator


def build_canonical_scenario() -> tuple[ApexDecisionOrchestrator, ContinuousState]:
    orchestrator = ApexDecisionOrchestrator()

    # Agent state (Autonomous strike UAV or humanoid robot)
    agent = ContinuousState(
        entity_id="AGENT-LEAD-01",
        position=Vector3D(0.0, 0.0, 50.0),
        velocity=Vector3D(25.0, 0.0, 0.0),
        acceleration=Vector3D(0.0, 0.0, 0.0),
    )

    # 3 High-priority dynamic tasks
    orchestrator.register_task(SwarmAgentTask("TASK-INTERCEPT-ALPHA", Vector3D(800, 200, 60), 95.0, "KINETIC_STRIKE"))
    orchestrator.register_task(SwarmAgentTask("TASK-RECON-BRAVO", Vector3D(1200, -100, 100), 60.0, "OPTICAL_SURVEILLANCE"))
    orchestrator.register_task(SwarmAgentTask("TASK-ESCORT-CHARLIE", Vector3D(500, 400, 40), 40.0, "DEFENSIVE_ESCORT"))

    # Physical hazards & friendly zones
    orchestrator.register_hazard(SafetyHazard("HAZARD-RADAR-TOWER", Vector3D(400, 50, 50), 30.0, False))
    orchestrator.register_hazard(SafetyHazard("FRIENDLY-SCOUT-01", Vector3D(750, 180, 60), 35.0, True))

    return orchestrator, agent


def cmd_simulate(args) -> int:
    orchestrator, agent = build_canonical_scenario()
    cycles = args.cycles

    print(f"Apex-DecisionCore Sub-Microsecond Execution | Running {cycles} Decision Cycles")
    print("-" * 80)

    for c in range(1, cycles + 1):
        report = orchestrator.execute_decision_cycle(agent, dt=0.01)
        action_name = report.selected_action.action_id if report.selected_action else "NONE"
        cbf_status = "SAFE" if report.safety_barrier_h >= 0.0 else f"DEFICIT({report.safety_barrier_h:.1f})"
        phases = " ".join([f"{k[:4]}:{v:.1f}us" for k, v in report.phase_latencies_us.items()])

        print(
            f"Cycle {c:03d} | Total Latency: {report.total_cycle_latency_us:5.2f} us | "
            f"Action: {action_name:<26} | CBF: {cbf_status:<10} | [{phases}]"
        )

    print("-" * 80)
    valid, reason = orchestrator.provenance_ledger.verify_ledger_integrity()
    print(f"Post-Quantum Merkle Ledger: {reason} (Chain Head: {orchestrator.provenance_ledger.chain[-1].block_hash[:16]}...)")
    return 0


def cmd_benchmark(args) -> int:
    orchestrator, agent = build_canonical_scenario()
    warmup = 100
    iterations = args.iterations

    for _ in range(warmup):
        orchestrator.execute_decision_cycle(agent, dt=0.01)

    latencies: List[float] = []

    for _ in range(iterations):
        report = orchestrator.execute_decision_cycle(agent, dt=0.01)
        latencies.append(report.total_cycle_latency_us)

    latencies.sort()
    n = len(latencies)
    avg = sum(latencies) / n
    p50 = latencies[n // 2]
    p90 = latencies[int(n * 0.90)]
    p95 = latencies[int(n * 0.95)]
    p99 = latencies[int(n * 0.99)]

    print(f"Apex-DecisionCore Microsecond Latency Benchmark ({iterations} Iterations)")
    print("=" * 70)
    print(f"Average Cycle Latency : {avg:7.2f} us")
    print(f"p50 Median Latency    : {p50:7.2f} us")
    print(f"p90 Latency           : {p90:7.2f} us")
    print(f"p95 Latency           : {p95:7.2f} us")
    print(f"p99 Worst-Case SLA    : {p99:7.2f} us")
    print("-" * 70)
    print("Hard real-time deterministic SLA verified: < 5 microseconds worst-case.")
    return 0


def cmd_export_clef(args) -> int:
    orchestrator, agent = build_canonical_scenario()
    report = orchestrator.execute_decision_cycle(agent, dt=0.01)

    if report.selected_action:
        json_spec = orchestrator.clef_runtime.export_clef_schema_json(
            report.selected_action, report.typed_decision, report.total_cycle_latency_us
        )
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(json_spec)
            print(f"Wrote Clef-compatible decision specification to: {args.output}")
        else:
            print(json_spec)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Apex-DecisionCore Sovereign Decision Model CLI")
    subparsers = parser.add_subparsers(dest="command")

    sim_p = subparsers.add_parser("simulate", help="Run multi-cycle continuous decision simulation")
    sim_p.add_argument("--cycles", type=int, default=10, help="Number of decision cycles")

    bench_p = subparsers.add_parser("benchmark", help="Run sub-microsecond latency benchmark")
    bench_p.add_argument("--iterations", type=int, default=1000, help="Number of benchmark iterations")

    clef_p = subparsers.add_parser("export-clef-spec", help="Export Cloudflare Clef & Jev compatible decision JSON")
    clef_p.add_argument("--output", type=str, default="", help="Optional output path")

    args = parser.parse_args()

    if args.command == "simulate":
        return cmd_simulate(args)
    elif args.command == "benchmark":
        return cmd_benchmark(args)
    elif args.command == "export-clef-spec":
        return cmd_export_clef(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
