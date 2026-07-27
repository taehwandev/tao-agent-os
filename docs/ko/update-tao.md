---
keyflow_id: docs_ko_update_tao
status: review
type: human-reviewed-needed
---

# Tao Agent OS 최신화 안내

이 문서는 한글 빠른 안내입니다. Tao Agent OS의 기준 정책은 `README.md`, `AGENTS.md`, `docs/skills/agent-bootstrap/SKILL.md`, `docs/skills/agent-runtime-integration/SKILL.md`에 있습니다.

## 기본 원칙

- Tao Agent OS는 복사해서 각 저장소에 붙여넣기보다, 하나의 root를 링크해서 쓰는 방식이 기본입니다.
- 개인이나 소수 사용자는 Git checkout 하나를 `git pull --ff-only`로 최신화하면 됩니다.
- Tao Agent OS를 링크한 대상 저장소는 별도 복사본을 업데이트할 필요가 없습니다. 다음 에이전트 작업 때 선택된 Tao Agent OS root의 최신 파일을 다시 읽으면 됩니다.
- 작업이 진행 중일 때 자동으로 pull하지 마세요. 지침이 중간에 바뀌면 작업 기준도 바뀝니다. 최신화는 작업 사이에 사람이 명시적으로 실행하는 것이 안전합니다.

## 경로 표기 원칙

- Git에 커밋되는 `AGENTS.md`, `CLAUDE.md`, `CODEX.md`, `.agents/README.md`같은 repo-local 지침에는 `/Users/.../tao-agent-os` 같은 개인 절대 경로를 넣지 마세요.
- 개인 로컬 공유 설치는 `${TAO_HOME}`으로 가리키고, 팀 고정 설치는 `.agents/tao-agent-os` 같은 repo-relative 경로를 사용하세요.
- 개인 절대 경로는 shell 환경변수 설정, 커밋하지 않는 사용자 전역 런타임 브리지, 또는 한 번만 붙여넣는 one-shot 프롬프트에서만 허용합니다.
- 기존에 커밋된 지침에서 개인 절대 경로를 발견하면 push 전에 portable reference로 바꿔야 합니다.

## 개인 로컬 설치 최신화

```bash
cd "${TAO_HOME}"
git pull --ff-only
~/.tao/bin/tao-hook workflow validate
vibeguard audit . --rules .
```

`TAO_HOME`을 쓰지 않는다면 실제 Tao Agent OS 경로로 이동해서 같은 명령을 실행하면 됩니다.

## 실행 근거 강제

최신화 후 여러 단계 작업을 맡길 때는 에이전트가 wrapper evidence를 만들게 하는 것이 안전합니다. 지침을 읽었다는 말만으로는 충분하지 않습니다.

작업 전에는 `~/.tao/bin/tao-hook start`를 한 번만 실행합니다. 이 명령이 라우팅과
preflight를 함께 수행하므로 성공 뒤에 `<TAO_LAUNCHER> workflow route`나
`<TAO_LAUNCHER> agent-preflight`를 따로 반복하지 않습니다:

에이전트 런타임에서 실행할 때는 `${TAO_HOME}`을 먼저 실제 절대 경로로 치환하세요. 승인 민감 명령에는 `$HOME`, `${HOME}`, `~`, 상대 경로를 남기지 않습니다.

```bash
~/.tao/bin/tao-hook start \
  --project . \
  --rules "${TAO_HOME}" \
  --command task \
  --request "<USER_REQUEST>"
```

start가 만든 route의 `required_docs`를 수정이나 검토 전에 직접 읽습니다.
의미 있는 수정 뒤에는 `<TAO_LAUNCHER> review` review hook을 실행하고,
남은 gate를 명시적 구조 상태로 기록한 다음 마무리 전에는 읽기 전용 finish
hook을 실행합니다:

```bash
~/.tao/bin/tao-hook gate-batch \
  --project . \
  --rules "${TAO_HOME}" \
  --gate-record '[{"gate":"orient","status":"SUCCESS","evidence":"<근거>"},{"gate":"scope","status":"SUCCESS","evidence":"<근거>"},{"gate":"act","status":"SUCCESS","evidence":"<근거>"},{"gate":"verify","status":"SUCCESS","evidence":"<근거>"},{"gate":"report","status":"SUCCESS","evidence":"<근거>"}]'

~/.tao/bin/tao-hook finish \
  --project . \
  --rules "${TAO_HOME}"
```

`finish`는 gate ledger를 쓰거나 덮어쓰지 않습니다. gate 상태 수정은
`gate`/`gate-batch`로만 기록하며, 각 gate의 가장 최신 구조 상태가 기준입니다.

`<TAO_LAUNCHER> workflow route`, `<TAO_LAUNCHER> agent-preflight`, `<TAO_LAUNCHER> agent-finish-check` 직접 호출은
hook이 unavailable인 경우의 하위(lower-level) 진단 또는 호환성 fallback일 뿐이며 같은
작업에서 두 번째 lifecycle로 실행하지 않습니다.

이 스크립트들은 대상 저장소의 `.tao/` 아래에 로컬 JSON 근거를 남깁니다. 보통 이 디렉터리는 커밋하지 않고 `.gitignore`에 둡니다. preflight 근거, finish-check 근거, route gate 근거가 없으면 결과물이 맞아 보여도 Tao Agent OS 기준으로는 non-compliant입니다. 사람이 보는 보고에는 두 가지 고양이 신호 배지만 씁니다: `🐱🟢 SUCCESS`는 근거와 함께 실행됨, `🐱🔴 FAIL`은 차단, 실패, 누락 또는 근거 없음입니다. 제3의 gate 상태는 보고하지 않습니다. `--request-classified`를 쓸 때는 `--classification-evidence`를 함께 남겨야 합니다. 다만 근거만으로는 이 플래그가 적용되지 않습니다. 이 플래그는 부모가 남긴 ready 상태의 유효한 execution capsule을 가진 위임 워커에게만 적용되며, 요청도 capsule도 없는 형태는 거부됩니다. 그 외의 호출자는 `--request "<USER_REQUEST>"`로 실제 사용자 요청을 넘기고 분류기가 판단하게 해야 합니다. 문서 목록과 라벨 컨텍스트만 필요하고 요청 인테이크를 주장하지 않는 호출자는 `--advisory`를 쓰며, 이는 어떤 다운스트림 게이트도 충족하지 않습니다. "그릴미"처럼 질문 드릴을 요청한 경우 드릴 근거가 없으면 `🐱🔴 FAIL`입니다.

VibeGuard가 `Needs review`이면 완료가 아닙니다. 그 상태를 명시 보고하고, 받아들일 수 있는 사유가 있을 때만 `--allow-vibeguard-review "<사유>"`로 finish check를 통과시킵니다.

## 팀 고정 버전 최신화

팀이 submodule이나 repo-pinned copy로 특정 버전을 고정했다면, 대상 저장소의 일반 리뷰 흐름으로 pinned commit을 올립니다.

```bash
cd <target-repo>
git submodule update --remote .agents/tao-agent-os
~/.tao/bin/tao-hook workflow validate
git add .agents/tao-agent-os
```

팀 저장소의 커밋, PR, 검증 정책은 대상 저장소 규칙을 따릅니다.

## 링크

- Tao Agent OS 사이트: `https://tao.thdev.app/#update`
- Tao Agent OS 저장소: `https://github.com/taehwandev/tao-agent-os`
- VibeGuard 사이트: `https://vibeguard.thdev.app/`
