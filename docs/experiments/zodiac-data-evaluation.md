<!--
SPDX-FileCopyrightText: Copyright 2026 SK TELECOM CO., LTD.
SPDX-License-Identifier: Apache-2.0
-->

# 조디악 데이터·평가 작업

> 목적: 라우터 변경이 실제로 좋아졌는지 품질·비용·재현성으로 검증한다.

## 완료한 결과

- 공개 데이터 materialization 완료: Train 1,760건 / Dev 880건
- 공식 테스트 완료: 261개 통과 / 19개 skip
- 제공 baseline 4개 공개 Dev 결과 재현
- 공식 `hash-regex` 학습을 Train에서 재실행
- 재학습 artifact의 공개 Dev 점수와 제공 artifact 결과 일치 확인
- `tools/zodiac_report.py` 추가: 표준 라이브러리만으로 집계 리포트 생성
- `tools/sweep_hash_regex_safety.py` 추가: tier별 예산 안전선 sweep

## 재현 명령

저장소 루트에서 실행한다.

```console
# 공개 입력 생성(처음 한 번)
.venv-data/bin/python tools/materialize_public_data.py

# 조디악 Dev 리포트
PYTHONPATH=src .venv-data/bin/python tools/zodiac_report.py \
  --input data/materialized/dev/inputs.json \
  --outcomes data/dev/outcomes.json \
  --baseline-dir build/public-dev \
  --output build/zodiac/data-evaluation-report.md

# Train으로 hash-regex artifact 재학습
PYTHONPATH=src .venv-data/bin/python baselines/train_hash_regex.py \
  --input data/materialized/train/inputs.json \
  --outcomes data/train/outcomes.json \
  --validation-input data/materialized/dev/inputs.json \
  --validation-outcomes data/dev/outcomes.json \
  --artifact build/zodiac/hash-regex-trained.json \
  --report build/zodiac/hash-regex-train-report.json

# 재학습 artifact로 Dev 제출 파일과 공식 점수 생성
mkdir -p build/zodiac/dev-submission
for tier in fast balanced premium; do
  PYTHONPATH=src .venv-data/bin/python baselines/hash_regex.py \
    --input data/materialized/dev/inputs.json \
    --artifact build/zodiac/hash-regex-trained.json \
    --tier "$tier" \
    --output "build/zodiac/dev-submission/$tier.json"
done

PYTHONPATH=src .venv-data/bin/python -m ossp_router.cli self-check \
  --input data/materialized/dev/inputs.json \
  --outcomes data/dev/outcomes.json \
  --submissions build/zodiac/dev-submission \
  --report build/zodiac/hash-regex-trained-dev-report.json

# tier별 safety ratio sweep
PYTHONPATH=src .venv-data/bin/python tools/sweep_hash_regex_safety.py \
  --artifact build/zodiac/hash-regex-trained.json \
  --tier premium \
  --output build/zodiac/safety-premium.md
```

## 확인된 수치

| 항목 | 결과 |
|---|---:|
| 재학습 Train self-check | 0.709730113636 |
| 재학습 artifact Dev final score | 0.695369318182 |
| Fast 비용 비율 | 1.235989091684 |
| Balanced 비용 비율 | 1.961506040268 |
| Premium 비용 비율 | 3.985204733480 |

재학습 결과가 제공된 `hash-regex-public.v1.json`과 동일한 Dev 점수를 내므로,
현재 baseline을 팀 환경에서 다시 만들 수 있다는 뜻이다. 다만 Premium은
공개 Dev 한도 4.0에 매우 가깝기 때문에 최종 제출 후보로 바로 고정하지 않는다.

## 조디악의 PR 검수 기준

라우터 PR마다 아래 네 가지를 확인하고 표로 남긴다.

1. 공식 테스트가 통과하는가?
2. 세 tier 제출 파일이 모두 생성되는가?
3. 공식 self-check에서 예산 초과가 없는가?
4. 변경 전후 final score와 tier별 비용 비율이 어떻게 달라졌는가?

점수가 올라도 비용 안전선을 넘으면 반려한다. 공개 Dev 점수만 반복해서
올리는 실험은 Train 내부 검증 결과와 함께 제시하지 않으면 채택하지 않는다.

## 첫 안전선 후보

재학습 artifact에 safety ratio를 적용해 공개 Dev에서 세 tier를 함께 평가했다.

| 후보 | Fast | Balanced | Premium | 최종 점수 | 판단 |
|---|---:|---:|---:|---:|---|
| 기본 artifact | 1.236 | 1.962 | 3.985 | 0.695369 | Premium 여유 부족 |
| 보수 후보 (`0.85 / 0.80 / 0.80`) | 1.068 | 1.686 | 3.495 | 0.680511 | 안전성 우선 |
| 균형 후보 (`0.90 / 0.85 / 0.85`) | 1.177 | 1.806 | 3.674 | 0.688750 | **첫 실험 추천** |

위 수치는 공개 Dev 기준이다. 균형 후보를 첫 제출용 후보로 두고, Train 내부
검증과 컨테이너 실행에서 문제가 없을 때만 공개 Dev 점수를 다시 확인한다.
공개 Dev 최고점인 기본 artifact를 바로 최종 제출 후보로 고정하지 않는다.

## 다음 담당자에게 넘길 분석 질문

- `ax31-light` 대비 `ax31` 또는 `axk1-think`의 score gain이 큰 episode를
  어떤 prompt 특징이 설명하는가?
- 현재 router가 올바른 승급 문항을 놓치는 이유는 난이도 feature 부족인가,
  cost 예측 오차인가?
- Premium에서 K1 선택을 줄였을 때 품질 손실과 예산 여유의 교환관계는
  어느 정도인가?

이 질문에 답하기 전에는 SBERT, ensemble, augmentation을 추가하지 않는다.
