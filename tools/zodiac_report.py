#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright 2026 SK TELECOM CO., LTD.
# SPDX-License-Identifier: Apache-2.0
"""Create a compact, reproducible data/evaluation report for team experiments.

This is an analysis-only tool. It never writes prompts, episode content, or model
decisions to the report; it writes aggregate statistics and episode IDs only.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from ossp_router.protocol import (
    MODEL_IDS,
    InputBatch,
    OutcomeBatch,
    RoutingPolicy,
    load_input,
    load_outcomes,
    load_policy,
)


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    ratio = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * ratio


def _episode_text(episode: Any) -> str:
    if episode.prompt is not None:
        return episode.prompt
    return "\n".join(message.content for message in episode.messages or ())


def _cost(outcome: Any, policy: RoutingPolicy) -> Decimal:
    rates = policy.models[outcome.model_id]
    unit = Decimal(policy.token_unit)
    return (
        rates.fixed_cost
        + Decimal(outcome.input_tokens) * rates.input_token_rate / unit
        + Decimal(outcome.output_tokens) * rates.output_token_rate / unit
    )


def _outcome_index(outcomes: OutcomeBatch) -> Mapping[tuple[str, str], Any]:
    return {
        (outcome.episode_id, outcome.model_id): outcome
        for outcome in outcomes.outcomes
    }


def _model_summary(
    inputs: InputBatch, outcomes: OutcomeBatch, policy: RoutingPolicy
) -> list[dict[str, Any]]:
    index = _outcome_index(outcomes)
    rows: list[dict[str, Any]] = []
    for model_id in MODEL_IDS:
        model_rows = [
            index[(episode.episode_id, model_id)] for episode in inputs.episodes
        ]
        rows.append(
            {
                "model_id": model_id,
                "average_score": sum(
                    (row.score for row in model_rows), Decimal("0")
                ) / len(model_rows),
                "average_input_tokens": sum(
                    row.input_tokens for row in model_rows
                )
                / len(model_rows),
                "average_output_tokens": sum(
                    row.output_tokens for row in model_rows
                )
                / len(model_rows),
                "total_cost": sum(
                    (_cost(row, policy) for row in model_rows), Decimal("0")
                ),
            }
        )
    light_cost = rows[0]["total_cost"]
    for row in rows:
        row["cost_ratio"] = row["total_cost"] / light_cost
    return rows


def _winner_summary(
    inputs: InputBatch, outcomes: OutcomeBatch
) -> tuple[Counter[str], Counter[str], list[dict[str, Any]]]:
    index = _outcome_index(outcomes)
    fractional: Counter[str] = Counter()
    strict: Counter[str] = Counter()
    opportunities: list[dict[str, Any]] = []
    for episode in inputs.episodes:
        rows = {
            model_id: index[(episode.episode_id, model_id)] for model_id in MODEL_IDS
        }
        best_score = max(row.score for row in rows.values())
        winners = [model_id for model_id, row in rows.items() if row.score == best_score]
        for model_id in winners:
            fractional[model_id] += 1 / len(winners)
        if len(winners) == 1:
            strict[winners[0]] += 1
        light_score = rows[MODEL_IDS[0]].score
        ax31_gain = rows["ax31"].score - light_score
        premium_gain = rows["axk1-think"].score - light_score
        if ax31_gain >= Decimal("0.5") or premium_gain >= Decimal("0.5"):
            opportunities.append(
                {
                    "episode_id": episode.episode_id,
                    "prompt_chars": len(_episode_text(episode)),
                    "ax31_gain": ax31_gain,
                    "premium_gain": premium_gain,
                }
            )
    opportunities.sort(
        key=lambda row: max(row["ax31_gain"], row["premium_gain"]), reverse=True
    )
    return fractional, strict, opportunities[:20]


def _load_reports(directory: Path) -> list[Mapping[str, Any]]:
    reports: list[Mapping[str, Any]] = []
    for path in sorted(directory.glob("*-report.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and "final_score" in value:
            reports.append({"name": path.stem.removesuffix("-report"), **value})
    return reports


def _fmt_decimal(value: Decimal, digits: int = 6) -> str:
    return f"{float(value):.{digits}f}"


def _fmt_number(value: float, digits: int = 1) -> str:
    return f"{value:,.{digits}f}"


def render_report(
    inputs: InputBatch,
    outcomes: OutcomeBatch,
    policy: RoutingPolicy,
    baseline_reports: Iterable[Mapping[str, Any]],
) -> str:
    texts = [_episode_text(episode) for episode in inputs.episodes]
    lengths = [len(text) for text in texts]
    summary = _model_summary(inputs, outcomes, policy)
    fractional, strict, opportunities = _winner_summary(inputs, outcomes)
    lines = [
        "# 조디악 데이터·평가 리포트",
        "",
        f"- split: `{inputs.split}`",
        f"- 문항 수: `{len(inputs.episodes):,}`",
        "- 분석 도구: `tools/zodiac_report.py` (표준 라이브러리만 사용)",
        "",
        "## 데이터 개요",
        "",
        "| 항목 | 값 |",
        "|---|---:|",
        f"| prompt 문자 수 최소 | {_fmt_number(min(lengths), 0)} |",
        f"| prompt 문자 수 중앙값 | {_fmt_number(_quantile(lengths, 0.5), 0)} |",
        f"| prompt 문자 수 p95 | {_fmt_number(_quantile(lengths, 0.95), 0)} |",
        f"| prompt 문자 수 최대 | {_fmt_number(max(lengths), 0)} |",
        "",
        "## 모델별 Train/Dev outcome 요약",
        "",
        "| 모델 | 평균 score | 평균 input tokens | 평균 output tokens | 전체 비용 비율 |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in summary:
        lines.append(
            "| {model_id} | {score} | {input_tokens} | {output_tokens} | {ratio} |".format(
                model_id=row["model_id"],
                score=_fmt_decimal(row["average_score"]),
                input_tokens=_fmt_number(row["average_input_tokens"]),
                output_tokens=_fmt_number(row["average_output_tokens"]),
                ratio=_fmt_decimal(row["cost_ratio"]),
            )
        )
    lines.extend(
        [
            "",
            "## 모델이 이긴 문항 수",
            "",
            "| 모델 | fractional win | strict win |",
            "|---|---:|---:|",
        ]
    )
    for model_id in MODEL_IDS:
        lines.append(
            f"| {model_id} | {fractional[model_id]:.1f} | {strict[model_id]} |"
        )
    lines.extend(["", "## 재현한 baseline 결과", ""])
    reports = list(baseline_reports)
    if reports:
        lines.extend(
            [
                "| baseline | final score | Fast 비용 | Balanced 비용 | Premium 비용 |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for report in reports:
            tiers = report.get("tiers", {})
            costs = [tiers.get(tier, {}).get("budget_ratio", "-") for tier in ("fast", "balanced", "premium")]
            lines.append(
                f"| {report['name']} | {report['final_score']} | {costs[0]} | {costs[1]} | {costs[2]} |"
            )
    else:
        lines.append("baseline report JSON을 찾지 못했습니다.")
    lines.extend(
        [
            "",
            "## 모델링 담당자에게 전달할 우선 분석 문항",
            "",
            "아래는 prompt 원문이 아니라 episode ID와 score 차이만 기록한 목록이다.",
            "",
            "| episode_id | prompt chars | ax31-light 대비 ax31 | ax31-light 대비 K1 |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in opportunities:
        lines.append(
            "| {episode_id} | {prompt_chars} | {ax31_gain} | {premium_gain} |".format(
                episode_id=row["episode_id"],
                prompt_chars=row["prompt_chars"],
                ax31_gain=_fmt_decimal(row["ax31_gain"], 3),
                premium_gain=_fmt_decimal(row["premium_gain"], 3),
            )
        )
    lines.extend(
        [
            "",
            "## 해석과 다음 실험",
            "",
            "1. 공개 Dev 최고점만 보지 않고 tier별 `budget_ratio`를 함께 본다.",
            "2. 위 opportunity 문항을 라우터가 놓치는 이유를 feature 단위로 태깅한다.",
            "3. Train 내부 검증에서 정책을 고른 뒤 공개 Dev는 최종 확인에만 사용한다.",
            "4. 비용 안전선 초과 또는 공식 테스트 실패가 있으면 점수 개선보다 먼저 수정한다.",
            "",
        ]
    )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="조디악 데이터·평가 Markdown 리포트 생성")
    parser.add_argument("--input", type=Path, default=root / "data/materialized/dev/inputs.json")
    parser.add_argument("--outcomes", type=Path, default=root / "data/dev/outcomes.json")
    parser.add_argument("--policy", type=Path, default=root / "configs/routing-policy.v1.json")
    parser.add_argument("--baseline-dir", type=Path, default=root / "build/public-dev")
    parser.add_argument("--output", type=Path, default=root / "build/zodiac/data-evaluation-report.md")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    inputs = load_input(args.input)
    outcomes = load_outcomes(args.outcomes)
    policy = load_policy(args.policy)
    report = render_report(inputs, outcomes, policy, _load_reports(args.baseline_dir))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"OK: 조디악 리포트를 생성했습니다: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
