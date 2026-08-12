---
keyflow_id: sys_figma_handoff_fidelity_limits
status: review
type: ai-generated
---

# 충실도(1:1)와 한계

이 도구가 Figma 디자인을 **픽셀·수치 기준으로 얼마나 재현**할 수 있는지, 어디까지 믿고 어디서 raw를 봐야 하는지 정리합니다.

결론: **화면 골격(레이아웃/텍스트/색/이펙트)은 `design-summary.json`만으로 거의 1:1**이지만, 일부 정밀 속성은 `raw/nodes.json` 병행이 필요하고, 몇 가지는 Figma REST API 한계로 불가합니다.

## Tier 1 — summary만으로 1:1 신뢰 가능

- **Auto Layout 전면**: layoutMode/wrap/정렬(primary·counter·counterAxisAlignContent)/sizingMode/layoutSizing/itemSpacing/counterAxisSpacing/padding 4방향/cornerRadius(개별 포함)/min·max/constraints/clipsContent/overflowDirection.
- **크기**: `absoluteBoundingBox`(px, 2dp). 오차 ≤0.005px로 실용상 무손실.
- **텍스트**: fontFamily/PostScriptName/weight/size/italic, lineHeight(PIXELS·FONT_SIZE_%·PERCENT 단위 구분 보존), letterSpacing, 정렬(H·V), autoResize, decoration/case/truncation/maxLines. 부분 스타일은 `textRuns`.
- **색상**: fill/stroke SOLID hex(#RRGGBBAA, paint.opacity×color.a 합성).
- **그라데이션 기하**: stops + handlePositions 원본(각도가 틀려도 handle로 정확 재계산).
- **effect 수치**: shadow color/offset/radius/spread, blur radius.
- **시각 속성(v2 추가)**: `opacity`, `blendMode`, `isMask`/`maskType`, `rotation`, `strokeWeight`, `strokeAlign`, `individualStrokeWeights`, `absoluteRenderBounds`.

## Tier 2 — summary 값 + 보정/raw 참조가 필요

- **노드 opacity**: `layoutNodes[].opacity`에 있으나 색 hex에는 **미반영**. 반투명 오버레이/디밍은 이 값을 별도로 곱해 적용.
- **회전 노드 크기**: `absoluteBoundingBox`는 회전 포함 외접 박스. 실제 형상은 `size`(없으면 raw) + `rotation`(라디안!) 또는 `relativeTransform`으로 복원.
- **그라데이션 각도**: `angleDegrees`는 정규화 좌표 기반이라 비정사각 노드에서 시각 각도와 불일치 → `handlePositions × 실제 width/height`로 재계산.
- **blendMode**: MULTIPLY 등이면 단순 덮어쓰기와 색 결과가 다름 → 합성 모드 반영.
- **stroke 정렬**: `strokeAlign`(INSIDE/OUTSIDE/CENTER)이 실제 점유 크기에 영향 → 레이아웃 계산 시 반영.

## Tier 3 — API/도구 한계 (현재 불가, 별도 처리)

- **디자인 토큰 이름 (비-Enterprise)**: `/variables/local`은 Figma Enterprise 전용. 그 외 플랜에선 variable 이름/값이 비고 `VariableID:…`만 남음 → 팀의 시맨틱 토큰 매핑을 수동 연결. 원격 라이브러리 변수는 Enterprise여도 미수집.
- **Display P3 색공간**: P3 float이 sRGB hex로 그대로 기록(프로파일 변환 없음). 정밀 색은 raw의 원본 float.
- **image fill 비트맵**: `--include-image-fills`는 URL 맵만 저장, 원본 비트맵은 다운로드 안 함. 사진 리소스는 별도 확보.
- **MD 리포트 절단**: `design-handoff.md`는 항목별 상한(layoutNodes 120 등)으로 잘림 → 정확 수치는 `design-summary.json`.

## 아이콘/벡터/이미지 리소스

- 기본 실행은 **화면 프레임만** PNG로 렌더하고, 화면 내부 요소는 `assetCandidates`에 id/name만 남깁니다.
- `--export-assets`로 개별 추출(assets/). 최대 복구를 위해 다음을 자동 적용:
  - **순수 벡터/불리언 → SVG** (노드 opacity 등이 벡터에 포함됨).
  - **이미지 fill(사진/아바타) → PNG** (`--scale` 반영). Figma가 이 노드를 SVG로는 렌더하지 못하므로 PNG로 받습니다.
  - **조상 폴백**: 노드 자체가 렌더 null이면 `renderFallbackIds`(조상 체인, 화면 프레임 제외)를 순서대로 시도해 렌더되는 컨테이너로 복구합니다.
- 보존된 historical fixture의 과거 측정에서는 사진 14/14, 전체 후보 42/62가 확보됐습니다. 이 수치는 다른 Figma file의 보장값이 아니며 현재 bundle의 `coverage_report`를 다시 확인해야 합니다.
  - SF Symbol 글리프는 export 대상이 아니라 각 플랫폼 네이티브 심볼(SF Symbols / Material)로 구현.
  - 아이콘 내부 조각은 단독으로 무의미하며, 그 합성 아이콘 자체는 렌더 가능하면 이미 확보됩니다.
- **본질적 한계(Figma REST 제약)**: 인스턴스 깊숙한 leaf 벡터/글리프는 개별 API로도 null(단독 렌더 미지원). 굳이 픽셀이 필요하면 전체 프레임 SVG(`--format svg`)에 모든 벡터 path가 포함됩니다.

## 해상도(scale) 가이드

- 기본 `--scale 2.0`. Android xxhdpi(3x) 기준 원본이 필요하면 `--scale 3`(최대 4.0). 단, 대형 SECTION은 고배율에서 렌더 timeout이 나므로 개별 프레임만 높은 scale로 따로 뽑는 걸 권장(README의 대형 프레임 패턴 참조).
