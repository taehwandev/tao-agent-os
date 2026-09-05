// Human-readable stage groups, not a second router or an executable gate list.
// Contracts: scripts/workflow_catalog.py, scripts/workflow_gate_policy.py,
// common/skills/commit-workflow and common/skills/branch-cleanup.
export const workflowContent = {
  en: {
    label: "Choose a type of work",
    entry: ["Your request", "Read the project rules", "Choose a workflow"],
    entryLabel: "Before work starts",
    decision: "Unclear scope or missing permission? Ask before acting.",
    legend: "Arrows show execution order. Related checks are grouped into stages.",
    example: "Example request",
    output: "What you get",
    exception: "When to stop or retry",
    source: "Read the workflow rules",
    routes: {
      analysis: {
        name: "Analysis", command: "analysis", example: "Find out why this is slow.",
        summary: "Read and measure. Leave the code as it is.",
        steps: [
          ["Start read-only", "Record the request and the current repository state."],
          ["Inspect the cause", "Read the relevant code and measure the suspected bottleneck."],
          ["Check and finish", "Record findings and lessons. Confirm that repository content did not change."],
          ["Explain the result", "Separate what was measured from what still needs checking."]
        ],
        output: "Findings, measurements and remaining questions. No code changes.",
        exception: "If a fix is needed, get a request to change it and start the matching work route. Analysis does not silently become implementation.",
        source: "scripts/workflow_catalog.py"
      },
      change: {
        name: "Code changes", command: "feature / bugfix", example: "Fix this bug and add a regression test.",
        summary: "Agree on the change, implement it, then check the exact result.",
        steps: [
          ["Start and check safety", "Record the request and permissions. Run the VibeGuard audit."],
          ["Locate the code", "Read required guidance, locate the code to change and define the acceptance check."],
          ["Make the change", "Work inside the agreed scope. Split work only when file ownership is independent."],
          ["Test and review", "Run relevant checks, update affected docs and review the final diff."],
          ["Check and report results", "Record all required checks and the retrospective before reporting the result."]
        ],
        output: "A reviewed change, verification results and any remaining limits. Commit and publication need their own permission.",
        exception: "A failed required check blocks completion. Repair it once when safe and authorized, verify, then resume there. If the same failure returns, stop and explain it.",
        source: "workflows/skills/feature-implementation/references/current-guidance.md"
      },
      commit: {
        name: "Commit / PR", command: "commit", example: "Commit this, open a PR and merge it.",
        summary: "Review the prepared change. Do not restart implementation just to publish it.",
        steps: [
          ["Confirm the scope", "Check the branch, remote, requested actions and current verification evidence."],
          ["Stage and review", "Stage only the intended files, then review that exact staged state."],
          ["Complete pre-commit checks", "Record commit readiness and the retrospective. Finish before creating the commit."],
          ["Commit, then publish", "Create the commit. Push and open a PR only when requested; reuse an existing matching PR."],
          ["Merge if requested", "Check required reviews, CI and conflicts. Confirm the merged commit on the target branch."]
        ],
        output: "The commit, PR and merge result for the actions you authorized. No release tag or deployment is implied.",
        exception: "Changed files invalidate old review evidence. Unresolved findings or missing publication permission stop this path. Reuse tests only while the change they cover is unchanged.",
        source: "common/skills/commit-workflow/references/current-guidance.md"
      },
      cleanup: {
        name: "After a merge", command: "cleanup", example: "Remove the merged worktree and branch.",
        summary: "Check what was merged and what is still being used. Remove only confirmed targets.",
        steps: [
          ["Identify the targets", "Confirm ownership, the integration branch and permission to delete."],
          ["Verify the merge", "For a PR, match its merged state, base branch and recorded head to the fetched branch tip."],
          ["Check local work", "Keep dirty worktrees and protected branches. Account for local-only files before removal."],
          ["Remove and confirm", "Remove the eligible worktree, then its branch. Remote deletion needs an explicit request."],
          ["Finish and report", "Record the result and retrospective. List what was removed, retained and recoverable."]
        ],
        output: "A cleanup report and the deleted branch tips for recovery. No repeat code review or full test suite.",
        exception: "Not merged, tip moved, or uncommitted changes? Keep it. A merged PR is not permission to delete work added afterward.",
        source: "common/skills/branch-cleanup/references/current-guidance.md"
      }
    }
  },
  ko: {
    label: "작업 종류 선택",
    entry: ["사용자 요청", "프로젝트 지침 확인", "작업 종류 선택"],
    entryLabel: "작업을 시작하기 전에",
    decision: "범위가 불분명하거나 권한이 없으면, 실행 전에 먼저 묻습니다.",
    legend: "화살표는 실행 순서입니다. 관련된 확인 항목을 단계별로 묶었습니다.",
    example: "이렇게 요청하면",
    output: "작업 결과",
    exception: "멈추거나 다시 확인하는 경우",
    source: "자세한 작업 규칙",
    routes: {
      analysis: {
        name: "분석", command: "analysis", example: "왜 느린지 확인해줘.",
        summary: "코드를 읽고 측정합니다. 코드는 바꾸지 않습니다.",
        steps: [
          ["읽기 전용으로 시작", "요청과 현재 저장소 상태를 기록합니다."],
          ["원인 확인", "관련 코드를 읽고, 병목으로 의심되는 부분을 측정합니다."],
          ["확인 후 종료", "분석 결과와 회고를 기록하고 저장소 내용이 바뀌지 않았는지 확인합니다."],
          ["결과 설명", "측정한 사실과 아직 확인하지 못한 내용을 구분해서 보고합니다."]
        ],
        output: "분석 결과, 측정값, 남은 질문입니다. 코드 수정은 포함하지 않습니다.",
        exception: "수정이 필요하면 변경 요청을 받고 해당 작업 경로를 시작합니다. 분석 도중 임의로 코드를 고치지 않습니다.",
        source: "scripts/workflow_catalog.py"
      },
      change: {
        name: "코드 수정", command: "feature / bugfix", example: "이 버그를 고치고 회귀 테스트도 추가해줘.",
        summary: "무엇을 바꿀지 정하고 구현한 뒤, 바뀐 결과를 확인합니다.",
        steps: [
          ["작업 범위와 안전 확인", "요청과 허용 범위를 기록하고 VibeGuard 검사를 실행합니다."],
          ["수정할 코드 확인", "필수 지침을 읽고 수정 위치와 완료 조건을 정합니다."],
          ["구현", "정한 범위 안에서 바꿉니다. 서로 다른 파일에서 독립적으로 작업할 수 있을 때만 병렬로 나눕니다."],
          ["테스트와 리뷰", "관련 검사를 실행하고 문서를 갱신한 뒤 최종 변경분을 리뷰합니다."],
          ["결과 확인과 보고", "필수 검사 결과와 회고를 기록하고, 빠진 항목이 없는지 확인한 뒤 결과를 보고합니다."]
        ],
        output: "변경한 코드, 테스트·리뷰 결과, 아직 해결하지 못한 문제입니다. 커밋·푸시·PR은 별도로 요청받은 경우에만 진행합니다.",
        exception: "필수 검사가 실패하면 완료하지 않습니다. 안전하고 허용된 수정만 한 번 적용·검증하고 실패 지점부터 이어갑니다. 같은 실패가 반복되면 멈추고 설명합니다.",
        source: "workflows/skills/feature-implementation/references/current-guidance.md"
      },
      commit: {
        name: "커밋·PR", command: "commit", example: "커밋하고 PR 만들어서 머지해줘.",
        summary: "준비된 변경분을 확인해 반영합니다. 커밋 요청만으로 구현 절차를 다시 시작하지 않습니다.",
        steps: [
          ["반영 범위 확인", "브랜치, 원격 저장소, 요청한 동작, 기존 검증 결과를 확인합니다."],
          ["스테이징과 리뷰", "이번 작업 파일만 스테이징하고 그 상태를 리뷰합니다."],
          ["커밋 전 최종 확인", "리뷰·검증 결과와 회고를 기록하고, 빠진 항목이 없는지 확인한 뒤 커밋합니다."],
          ["커밋과 PR", "커밋을 만듭니다. 요청받은 경우에만 푸시하고 PR을 만들며, 같은 PR이 있으면 재사용합니다."],
          ["머지 요청 처리", "필수 리뷰, CI, 충돌 여부를 확인하고 대상 브랜치에 머지된 커밋을 확인합니다."]
        ],
        output: "허용한 동작에 대한 커밋, PR, 머지 결과입니다. 릴리스 태그나 배포까지 요청한 것으로 보지 않습니다.",
        exception: "파일이 바뀌면 이전 리뷰 결과를 그대로 쓰지 않습니다. 리뷰 지적이 남았거나 외부 반영 권한이 없으면 멈춥니다. 기존 테스트는 검증한 변경분이 그대로일 때만 재사용합니다.",
        source: "common/skills/commit-workflow/references/current-guidance.md"
      },
      cleanup: {
        name: "머지 후 정리", command: "cleanup", example: "머지한 워크트리와 브랜치 정리해줘.",
        summary: "머지 여부와 남은 작업을 확인하고, 지워도 되는 대상만 정리합니다.",
        steps: [
          ["정리 대상 확인", "작업 소유자, 기준 브랜치, 삭제 권한을 확인합니다."],
          ["머지된 커밋 확인", "PR이 어느 브랜치에 머지됐는지 확인합니다. 원격 정보를 갱신한 뒤, 삭제할 브랜치의 최신 커밋이 PR에 기록된 커밋과 같은지 비교합니다."],
          ["삭제해도 되는지 확인", "커밋하지 않은 변경이나 로컬에만 있는 파일을 확인합니다. 남은 작업이 있거나 보호된 브랜치라면 삭제하지 않습니다."],
          ["삭제 후 확인", "확인된 워크트리부터 제거하고 브랜치를 지웁니다. 원격 브랜치는 명시적으로 요청받은 경우에만 삭제합니다."],
          ["정리 결과 보고", "정리 결과와 회고를 기록하고 마지막으로 확인합니다. 지운 것, 남긴 것, 복구 방법을 보고합니다."]
        ],
        output: "정리 결과와 복구에 필요한 브랜치 커밋입니다. 코드 리뷰나 전체 테스트를 다시 하지 않습니다.",
        exception: "미머지, 커밋 변경, 미커밋 작업이 확인되면 남깁니다. PR이 머지됐어도 그 뒤에 추가한 작업까지 지우지는 않습니다.",
        source: "common/skills/branch-cleanup/references/current-guidance.md"
      }
    }
  }
};
