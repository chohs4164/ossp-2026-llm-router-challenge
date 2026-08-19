#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright 2026 SK TELECOM CO., LTD.
# SPDX-License-Identifier: Apache-2.0
"""Sweep hash-regex safety ratios and report the quality/cost trade-off."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "baselines"))

import hash_regex  # noqa: E402
from ossp_router.protocol import (  # noqa: E402
    TIERS,
    load_bundled_policy,
    load_input,
    load_outcomes,
)
from ossp_router.scoring import score_submissions  # noqa: E402


RATIOS = (0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.925, 0.95, 0.975, 1.0)


def sweep(
    *, input_path: Path, outcomes_path: Path, artifact_path: Path, tier: str
) -> list[dict[str, str]]:
    inputs = load_input(input_path)
    outcomes = load_outcomes(outcomes_path)
    policy = load_bundled_policy()
    artifact = hash_regex.load_artifact(artifact_path)
    rows = []
    for ratio in RATIOS:
        safety = dict(artifact.tier_safety_ratios)
        safety[tier] = ratio
        candidate = replace(artifact, tier_safety_ratios=safety)
        submissions = [
            hash_regex.make_hash_regex_submission(
                inputs, policy, candidate, current_tier
            ).submission
            for current_tier in TIERS
        ]
        report = score_submissions(inputs, outcomes, submissions, policy)
        tier_report = report["tiers"][tier]
        rows.append(
            {
                "safety_ratio": f"{ratio:.3f}",
                "final_score": report["final_score"],
                "tier_score": tier_report["tier_score"],
                "budget_ratio": tier_report["budget_ratio"],
                "budget_passed": str(tier_report["budget_passed"]).lower(),
                "model_counts": ", ".join(
                    f"{model}={count}"
                    for model, count in tier_report["model_counts"].items()
                ),
            }
        )
    return rows


def render(rows: list[dict[str, str]], tier: str) -> str:
    lines = [
        "# hash-regex 예산 안전선 sweep",
        "",
        f"대상 tier: `{tier}`. 다른 tier는 artifact의 기본 안전계수를 유지했다.",
        "",
        "| safety ratio | final score | tier score | 실제 비용 비율 | 통과 | 모델 선택 수 |",
        "|---:|---:|---:|---:|:---:|---|",
    ]
    for row in rows:
        lines.append(
            "| {safety_ratio} | {final_score} | {tier_score} | {budget_ratio} | "
            "{budget_passed} | {model_counts} |".format(**row)
        )
    lines.extend(
        [
            "",
            "해석: safety ratio를 낮추면 보통 비용 여유는 커지지만 선택 모델이 "
            "light 쪽으로 이동해 품질이 떨어질 수 있다. 공개 Dev에서 가장 높은 "
            "점수만 고르지 말고, 비공개 데이터 변동을 견딜 여유를 함께 검토한다.",
        ]
    )
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="hash-regex tier safety sweep")
    parser.add_argument("--input", type=Path, default=root / "data/materialized/dev/inputs.json")
    parser.add_argument("--outcomes", type=Path, default=root / "data/dev/outcomes.json")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--tier", choices=TIERS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    report = render(
        sweep(
            input_path=args.input,
            outcomes_path=args.outcomes,
            artifact_path=args.artifact,
            tier=args.tier,
        ),
        args.tier,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"OK: safety sweep를 생성했습니다: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
