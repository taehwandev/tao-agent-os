---
keyflow_id: sys_figma_handoff_summary_schema
status: review
type: ai-generated
---

# design-summary.json 필드 레퍼런스

`design-handoff.md`(사람이 읽는 요약)와 달리, **`summary/design-summary.json`이 전체 수치의 source of truth**입니다. MD는 항목별로 잘려 있으니(예: layoutNodes 120개 절단) 정확한 값은 항상 JSON을 봅니다.

이 문서는 그 JSON의 필드가 **어떤 단위·좌표계·의미**인지 정의합니다. `manifest.json`의 `schemaVersion`으로 구조 버전을 확인하세요 (현재 `3`).

## 공통 규칙

- **수치 반올림**: 모든 px/각도 수치는 소수점 2자리까지(`round_number`, figma_util.py). 정수에 가까우면 int로 저장. 최대 오차 ~0.005px.
- **좌표 단위**: 별도 표기 없으면 Figma 파일 캔버스 좌표계의 px.
- **null**: Figma REST가 값을 주지 않으면 필드가 없거나 null. "없음"과 "0"은 구분됩니다.
- **파일 경로**: `screens[].imagePath`와 `assetCandidates[].assetPath`는 bundle root 기준 POSIX 상대경로입니다. 개인 절대경로나 Agent OS checkout 위치에 의존하지 않습니다.

## top-level 키

| 키 | 의미 |
|---|---|
| `meta` | fileKey / startNodeId / sourceUrl / generatedAt(UTC ISO) |
| `screens` | 렌더 대상 화면(프레임)별 id/name/type/width/height/imagePath |
| `flowEdges` | prototype 전환 간선 (from→to) |
| `flowInteractions` | trigger/action/navigation/transition 상세 |
| `designTokens` | named color/text/effect 스타일 + variables |
| `referencedStyles` | 노드 payload의 `styles` 참조 기반 스타일 카탈로그(원격 라이브러리 복구용) |
| `components` | **화면에서 실제 사용된 컴포넌트 인벤토리(컴포넌트화 work-list)** — 사용 빈도순 |
| `componentBlueprints` | **컴포넌트별 내부 구조 청사진**(대표 인스턴스 서브트리) — 이대로 조립 |
| `colors` / `gradients` / `textStyles` / `effects` | 사용 빈도 기준 후보 |
| `textRuns` | 부분 텍스트 스타일 override run |
| `layoutMetrics` | padding/spacing/정렬 값의 빈도 집계 |
| `layoutNodes` | **노드별 레이아웃·시각 속성 (구현의 핵심)** |
| `assetCandidates` | 아이콘/벡터/이미지 fill 후보 (+`--export-assets` 시 `assetPath`) |
| `assetInventory` | assetCandidates를 dedupKey로 묶은 **고유 아이콘 인벤토리**(반복 구현 방지) |
| `warnings` | 이번 실행에서 스킵/실패한 항목 |

## layoutNodes[] — 노드별 속성

각 항목: `id`, `name`, `type`, `parentId`, `depth` + 아래 필드(노드에 존재할 때만).

### 컴포넌트 정체성 (INSTANCE 노드)
- `componentId`: 이 인스턴스가 참조하는 컴포넌트(마스터)의 node id (`components[]`의 `componentId`와 매칭). id는 `slug:num` colon 형식으로 정규화.
- `componentProperties`: variant/text/boolean/instance-swap 등 이 인스턴스의 속성을 `{이름: 값}`으로 평탄화(Figma 원본 `{이름:{value,type}}`에서 `value`만 추출).

### 크기·위치·회전
- `absoluteBoundingBox` `{x,y,width,height}`: 캔버스 좌표계 AABB. **회전된 노드는 이 박스가 회전 포함 외접 사각형**이라 실제 폭/높이와 다릅니다.
- `absoluteRenderBounds` `{x,y,width,height}`: 그림자/blur 등 이펙트가 밖으로 나간 실제 렌더 범위. bounding box보다 큽니다.
- `size` `{x,y}`: 노드 자체의 회전 전 폭/높이. 회전 노드는 `absoluteBoundingBox` 대신 `size` + `rotation`/`relativeTransform`으로 실제 형상을 복원합니다. (REST가 안 줄 때가 있음 → 없으면 raw/nodes.json 참조)
- `rotation`: **라디안(radian)** 단위. degree = `rotation * 180 / π`. 예: `3.14` ≈ π = 180°. 정확한 방향·기울임은 `relativeTransform`(2×3 affine 행렬)이 authoritative.
- `relativeTransform`: 부모 기준 2×3 변환 행렬 `[[a,c,tx],[b,d,ty]]`.

### 레이아웃 (Auto Layout)
- `layoutMode` HORIZONTAL/VERTICAL/NONE, `layoutWrap` WRAP/NO_WRAP
- `primaryAxisAlignItems` / `counterAxisAlignItems` / `counterAxisAlignContent`(wrap 줄 정렬)
- `primaryAxisSizingMode` / `counterAxisSizingMode` FIXED/AUTO
- `layoutSizingHorizontal` / `layoutSizingVertical` FIXED/HUG/FILL
- `layoutPositioning` AUTO/ABSOLUTE, `layoutAlign`, `layoutGrow`
- `itemSpacing`, `counterAxisSpacing`, `paddingTop/Right/Bottom/Left` (px)
- `minWidth/maxWidth/minHeight/maxHeight`
- `constraints` `{horizontal,vertical}` MIN/MAX/CENTER/STRETCH/SCALE — 리사이즈 규칙

### 모양·시각
- `cornerRadius` 또는 `rectangleCornerRadii` `[tl,tr,br,bl]` (개별 코너 우선)
- `clipsContent`, `overflowDirection`
- `opacity`: **노드 레벨 불투명도(0..1)**. ⚠️ `colors`/fill hex에는 반영돼 있지 **않습니다** — 이 값을 별도로 곱해 적용하세요.
- `blendMode`: PASS_THROUGH/MULTIPLY 등. MULTIPLY 등이면 단순 색 덮어쓰기와 결과가 다릅니다.
- `isMask` / `maskType`: 마스크(클리핑) 노드 여부.
- `strokeWeight`: 보더 두께(px, 비정수 가능 예 0.99).
- `strokeAlign`: INSIDE/OUTSIDE/CENTER — 두께가 박스 안/밖/중앙 어디로 그려지는지. 크기 계산에 영향.
- `individualStrokeWeights` `{top,right,bottom,left}`, `strokeDashes` (점선 패턴).

## 색상 (`colors[]`, hex 규칙)

- `hex`: `#RRGGBB` 또는 `#RRGGBBAA`.
- **알파 합성** = `paint.opacity × color.a`. 노드 레벨 opacity는 미포함(위 참조).
- alpha ≥ 0.995는 6자리(#RRGGBB)로 절삭. `#…00`(완전 투명)은 후보에서 제외.
- ⚠️ 문서가 Display P3 프로파일이면 P3 값이 sRGB hex로 그대로 기록됩니다(색 프로파일 미처리). 정밀 색은 raw/nodes.json의 원본 float 참조.
- `boundVariableNames` / `boundVariableIds`: 이 색에 바인딩된 디자인 토큰(variable). 이름은 Variables fetch 성공 시에만 채워집니다.

## 그라데이션 (`gradients[]`)

- `type`, `stops[]` `{position(0..1), hex}`, `handlePositions[]` `{x,y}`.
- `handlePositions`는 **노드 바운딩박스 기준 0..1 정규화 좌표**(px 아님).
- `angleDegrees`(LINEAR만): 0°=위, 시계방향. **정규화 좌표 기반**이라 정사각형이 아닌 노드에서는 화면상 시각 각도와 다릅니다 → 정확한 각도는 `handlePositions × 노드 실제 width/height`로 재계산.
- RADIAL/ANGULAR/DIAMOND는 각도/반지름 해석 없이 handle만 기록.

## 텍스트 (`textStyles[]`, `textRuns[]`, designTokens.textStyles)

- `fontFamily`, `fontPostScriptName`, `fontWeight`, `fontSize`(px), `italic`(bool).
- **lineHeight 우선순위**: `lineHeightPx`(단위 PIXELS) → `lineHeightPercentFontSize`(FONT_SIZE_%) → `lineHeightPercent`(PERCENT). `lineHeightUnit`도 함께 기록.
- `letterSpacing`(수치) + `letterSpacingUnit`(PERCENT거나 null). null이면 px로 취급(Figma 기본).
- `textAlignHorizontal`, `textAlignVertical`, `textAutoResize`(NONE/HEIGHT/WIDTH_AND_HEIGHT/TRUNCATE), `textDecoration`, `textCase`, `textTruncation`, `maxLines`, `paragraphSpacing`.
- `textRuns[]`: 한 텍스트 노드 안의 부분 스타일. `range{start,end}` + `text` + `resolvedStyle`(base+override 병합).

## Variables (`designTokens.variables`)

- `collections[]` `{id,name,modes[],defaultModeId}`, `variables[]` `{id,name,resolvedType,collectionId,valuesByMode}`.
- `valuesByMode[modeId]`:
  - COLOR 직접값: `{hex, raw}`
  - alias: `{alias, aliasId, aliasName:"Collection/Name", resolvedHex? | resolvedAliasName?}` — alias chain을 재귀 resolve(cycle guard, 모드 없으면 defaultMode 폴백).
- ⚠️ `/variables/local`은 **Figma Enterprise 플랜 전용**. 비-Enterprise면 `variables`가 비고 warnings에 안내가 남으며, `colors[].boundVariableIds`에 `VariableID:…`만 남고 이름은 비어 있습니다.

## assetCandidates[]

- `id`, `name`, `type`(VECTOR/BOOLEAN_OPERATION 등), `exportSettings`, `imageRefs`(이미지 fill의 imageRef).
- `dedupKey`: 시각 시그니처(geometry+색+name 해시 또는 `img:<imageRef>`). 같은 키 = 동일 아이콘.
- `nearestComponentName`: 이 asset을 감싸는 **가장 가까운 컴포넌트 인스턴스의 이름**(있을 때). 이름 없는 벡터(`Vector`)라도 이 값으로 정체를 파악합니다.
- `renderFallbackIds`: `[{id,name}]` — 이 노드가 단독 렌더 실패할 때 시도할 조상 컨테이너 체인(화면 프레임 제외, 최대 3단계). `--export-assets`가 이걸로 폴백 복구합니다.
- `--export-assets` 실행 시 렌더된 개별 파일 경로가 `assetPath`로 주입됩니다. 포맷은 타입별로 분기됩니다:
  - `imageRefs`가 있는 이미지 fill 노드(사진/아바타) → **PNG**(`--scale` 반영). Figma는 이런 노드를 SVG로 렌더하지 못합니다.
  - 순수 벡터/불리언 → **SVG**.
  - 노드 자체가 null이면 `renderFallbackIds` 조상으로 폴백. 그래도 실패하면 warnings에 기록됩니다(대개 SF Symbol 글리프·아이콘 내부 geometry 조각 = export 대상 아님).

## assetInventory[] — 고유 아이콘 인벤토리 (반복 구현 방지)

`assetCandidates`를 `dedupKey`로 묶어 **동일 아이콘을 한 항목으로** 집계합니다. 같은 아이콘을 여러 화면에서 반복 구현하지 않도록, 이 목록의 고유 아이콘만 에셋으로 만들면 됩니다.

각 항목:
- `dedupKey`: 그룹 키(시각 시그니처 또는 imageRef).
- `name`: 대표 이름. member 이름이 전부 generic(`Vector`/`Group` 등)이면 `nearestComponentName`으로 복구.
- `type`, `usageCount`(묶인 인스턴스 수), `nodeIds`(member 노드 id 목록).
- `nameUnclear`: member 이름이 전부 generic이면 `true` → 의미 명명이 필요한 아이콘(에이전트가 렌더 PNG를 보고 명명).
- `nearestComponentName` / `imageRefs`: 포함 컴포넌트 이름 / 이미지 fill 참조(있을 때).

> 의미 있는 아이콘 이름("검색 아이콘")은 이 도구가 부여하지 않습니다. `nameUnclear=true`이고 `nearestComponentName`도 없는 아이콘은, 소비 에이전트가 `--export-assets`로 렌더한 PNG를 보고 명명하세요(dedup 덕에 고유 개수만 보면 됩니다).

## componentBlueprints[] — 컴포넌트 내부 구조 청사진

각 distinct 컴포넌트를 **어떻게 조립하는지**를 대표 인스턴스(자식이 가장 많은 인스턴스)의 내부 서브트리로 넘깁니다. 화면을 범용 레이아웃으로 손으로 재구성하지 말고, 이 청사진대로 각 컴포넌트를 **한 번** 만든 뒤 인스턴스로 배치하세요.

각 항목:
- `componentId`, `name`(componentSetName 우선), `usageCount`, `representativeInstanceId`, `size{w,h}`, `variantProperties`.
- `structure[]`: 대표 인스턴스의 자식 노드들. 각 노드 `{name, type, depth, w, h}` + 상황별:
  - `componentId`: 이 노드가 **중첩 인스턴스**면 그 컴포넌트 id. **내부는 펼치지 않습니다**(각 컴포넌트는 자기 청사진이 있음) → 조합형으로 유지. 예: 카드 청사진 안의 `Icon/HeartToggle`은 `componentId:17:981` 참조로만 나오고, `Icon/LikeToggle`(17:985)과 **절대 합쳐지지 않습니다**.
  - `assetDedupKey`: 이 노드가 asset이면 `assetInventory`/`assetCandidates`의 dedupKey. 어느 아이콘/이미지 파일인지 연결.
  - `text`: TEXT 노드면 실제 문자열 샘플(40자).

> 구현 규칙: 컴포넌트별로 자기 청사진 + 자기 asset(`assetDedupKey`)으로 만들고, **중첩 인스턴스(componentId)는 서로 다른 컴포넌트면 다른 구현**입니다. 한 아이콘을 모든 자리에 재사용하지 마세요.

## components[] — 컴포넌트 인벤토리 (컴포넌트화 work-list)

이 프레임에서 **실제 인스턴스로 사용된** 컴포넌트를 `componentId` 기준으로 묶어 집계합니다. 화면 전체를 한 번에 재현하는 대신, 이 목록을 사용 빈도순 work-list로 삼아 상위부터 하나씩 코드 컴포넌트(Compose/SwiftUI/CSS)로 정의하면, 그 컴포넌트를 쓰는 모든 화면이 동시에 정확해집니다.

각 항목:
- `componentId`: 컴포넌트(마스터) node id. 화면의 `layoutNodes[].componentId`가 이걸 가리킵니다.
- `name`: 컴포넌트 이름. variant 멤버는 이 값이 variant 문자열(예 `type=off`)이고, 진짜 이름은 `componentSetName`입니다.
- `usageCount`: 이 컴포넌트를 참조하는 인스턴스 총 개수.
- `usedInScreens`: 사용된 화면(프레임) id 목록.
- `componentSetId` / `componentSetName`: variant 묶음(Component Set)에 속하면 그 셋의 id/이름 = **코드에서 하나의 컴포넌트로 만들 단위**. variant는 파라미터로 흡수.
- `variantProperties`: `{속성:값}`. VARIANT 타입 속성만(예 `{state: on/off}`). 코드 컴포넌트의 상태 파라미터 후보.
- `description` / `remote`: Figma 컴포넌트 설명, 원격 라이브러리 컴포넌트 여부(있을 때만).

> variant 멤버 각각이 별도 항목입니다. 하나의 코드 컴포넌트로 묶으려면 `componentSetId`로 그룹핑하세요.

## 함께 보기

- 라디안 회전·회전 노드·개별 stroke 두께 등 정밀 형상은 `raw/nodes.json`(원본 API 응답 전체)이 최종 근거입니다.
- 이 도구가 재현하지 못하는 항목은 `fidelity-and-limits.md` 참조.
