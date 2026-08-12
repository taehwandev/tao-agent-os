---
keyflow_id: sys_figma_handoff_verification
status: review
type: ai-generated
---

# 검증 하네스

Figma handoff는 네트워크 없는 회귀, 생성 bundle 검증, 선택적 live smoke의 세 층으로 검증한다. 특정 팀의 token이나 Figma file을 기본 fixture로 요구하지 않는다.

## 1. 오프라인 회귀

`tests/`는 `request_json`과 `download_file`을 mock해 실제 네트워크를 사용하지 않는다.

- `test_figma_handoff.py`: URL/node, fetch batch, flow, style, variable, asset format과 fallback 단위 회귀
- `test_asset_dedup_parallel.py`: asset signature dedup, batch와 상한 회귀
- `test_fidelity_harness.py`: 회전, opacity, stroke, mask, blend, gradient, variable alias와 text run을 포함한 합성 golden fixture
- `test_discovery_detail_example.py`: 추천 Web sample의 결정적 생성과 로컬 asset 연결
- `test_example_boundaries.py`: 정식 Web sample만 남는 예제 경계, 숨김 로컬 작업 공간의 ignore 규칙과 실행 코드 독립성
- `test_standalone.py`: 다른 작업 디렉터리와 Python isolated mode에서의 dry-run, 기본 출력과 오류 정보 안전성

```bash
cd tools/figma-handoff
python3 -m py_compile figma-handoff.py figma_*.py live_smoke.py
python3 -m unittest discover -s tests
```

모든 offline test는 token과 Bitbucket/Figma 네트워크 없이 통과해야 한다. 새 fetch 기능도 network mock을 경유한다.

## 2. Bundle 검증기

`figma_validate.py`는 임의의 `design-summary.json`을 읽어 schema 불변식과 충실도 coverage를 계산한다.

```bash
python3 tools/figma-handoff/figma_validate.py \
  <bundle>/summary/design-summary.json
```

- 종료 `0`: schema 위반 없음
- 종료 `1`: schema 불변식 위반
- 종료 `2`: 인자 또는 파일 읽기 실패

CLI는 생성 도중에도 같은 validator를 호출하고 문제를 `warnings`와 stderr에 남긴다. 새 summary 필드를 추가하거나 의미를 바꾸면 validator, schema 문서와 합성 fixture를 함께 갱신한다.

## 3. Live smoke

`live_smoke.py`는 실제 Figma API를 사용해 frame download, asset format 분기와 image-fill recovery를 확인한다. 재사용 가능한 공개 기본 URL을 내장하지 않으며 팀이 소유한 작은 frame URL을 명시해야 한다.

```bash
FIGMA_TOKEN=... python3 tools/figma-handoff/live_smoke.py \
  --url "$FIGMA_SMOKE_URL" --scale 3
```

`--quick`은 asset export를 생략하고 schema, frame PNG와 layout coverage만 확인한다. `--token-env`로 별도 token 환경변수를 선택할 수 있다.

- token 환경변수가 없으면 `SKIP`과 종료 `0`
- token이 있는데 URL이 없으면 사용 오류
- 실제 산출물은 임시 디렉터리에 만들고 종료 시 제거
- signed render URL과 token은 출력하지 않음

실제 API가 필요한 기능을 바꿨다면 offline test 통과만으로 live 동작을 확정하지 않는다. 반대로 token이 없는 CI에서는 live smoke skip을 실패로 처리하지 않는다.

## 4. 문서와 독립성 검증

릴리스 전에는 다음도 확인한다.

- skill과 tool의 Markdown link가 Agent OS 내부 존재 파일을 가리키는지
- 범용 실행 문서에 외부 CLI 저장소, 개인 절대경로, 특정 AI runtime fallback이 없는지
- `.figma-handoff-work/`, legacy `output/`, token, signed URL 또는 Python cache가 추적 대상에 들어오지 않았는지
