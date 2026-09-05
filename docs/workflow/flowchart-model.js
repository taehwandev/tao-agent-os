// Presentation topology only. Detailed stage descriptions retain their rule links.
// Rows are shared by both languages; edges explicitly name their source and target.
const charts = {
  analysis: {
    nodes: [
      ['start', 'terminal', ['Analysis request', '분석 요청'], 0],
      ['inspect', 'process', ['Read & measure', '코드 읽기·측정'], 1],
      ['clean', 'decision', ['No file changes?', '파일 변경 없음?'], 2],
      ['finish', 'process', ['Record & check results', '결과 정리·최종 확인'], 3],
      ['done', 'terminal', ['Report findings', '분석 결과 보고'], 4],
      ['stop', 'terminal', ['Stop & report changes', '중단 후 변경 보고'], 2, 'side']
    ],
    edges: [
      ['start', 'inspect'], ['inspect', 'clean'], ['clean', 'finish', 'yes'],
      ['finish', 'done'], ['clean', 'stop', 'no']
    ]
  },
  change: {
    nodes: [
      ['start', 'terminal', ['Change request', '수정 요청'], 0],
      ['scope', 'process', ['Check scope & safety', '작업 범위·안전 확인'], 1],
      ['edit', 'process', ['Implement', '코드 수정'], 2],
      ['test', 'process', ['Test & review', '테스트·리뷰'], 3],
      ['pass', 'decision', ['Checks pass?', '검사 통과?'], 4],
      ['finish', 'process', ['Record & check results', '검증 기록·최종 확인'], 5],
      ['done', 'terminal', ['Report changes', '변경 사항 보고'], 6],
      ['repair', 'process', ['Fix & verify', '오류 수정·재검증'], 2, 'side'],
      ['recover', 'decision', ['Safe to retry?', '다시 수정 가능?'], 4, 'side'],
      ['stop', 'terminal', ['Stop & explain why', '중단 사유 보고'], 6, 'side']
    ],
    edges: [
      ['start', 'scope'], ['scope', 'edit'], ['edit', 'test'], ['test', 'pass'],
      ['pass', 'finish', 'yes'], ['finish', 'done'], ['pass', 'recover', 'no'],
      ['recover', 'repair', 'yes'], ['recover', 'stop', 'no'],
      ['repair', 'test', 'retry', 'retry']
    ]
  },
  commit: {
    nodes: [
      ['start', 'terminal', ['Commit request', '커밋 요청'], 0],
      ['review', 'process', ['Stage & review changes', '변경분 스테이징·리뷰'], 1],
      ['ready', 'decision', ['Ready to commit?', '커밋 준비 완료?'], 2],
      ['commit', 'process', ['Final check → commit', '최종 확인 → 커밋'], 3],
      ['publish', 'decision', ['Push / PR requested?', '푸시·PR도 요청?'], 4],
      ['pr', 'process', ['Push & open PR', '푸시·PR 생성'], 5],
      ['merge', 'decision', ['Merge approved & ready?', '머지 승인·준비 완료?'], 6],
      ['done', 'terminal', ['Merge & confirm', '머지·결과 확인'], 7],
      ['stop', 'terminal', ['Stop & report issues', '리뷰 문제 보고'], 2, 'side'],
      ['local', 'terminal', ['Local commit only', '로컬 커밋으로 종료'], 4, 'side'],
      ['pending', 'terminal', ['Leave PR open & report', 'PR 남기고 상태 보고'], 6, 'side']
    ],
    edges: [
      ['start', 'review'], ['review', 'ready'], ['ready', 'commit', 'yes'],
      ['ready', 'stop', 'no'], ['commit', 'publish'], ['publish', 'pr', 'yes'],
      ['publish', 'local', 'no'], ['pr', 'merge'], ['merge', 'done', 'yes'],
      ['merge', 'pending', 'no']
    ]
  },
  cleanup: {
    nodes: [
      ['start', 'terminal', ['Cleanup request', '정리 요청'], 0],
      ['targets', 'process', ['Targets & permission', '대상·삭제 권한 확인'], 1],
      ['merged', 'decision', ['Matches merged commit?', '머지된 커밋과 같음?'], 2],
      ['clean', 'decision', ['Safe to delete?', '삭제해도 안전?'], 3],
      ['remove', 'process', ['Worktree → branch', '워크트리 → 브랜치 삭제'], 4],
      ['done', 'terminal', ['Check & report cleanup', '정리 결과 확인·보고'], 5],
      ['unmerged', 'terminal', ['Keep & explain why', '남겨두고 이유 설명'], 2, 'side'],
      ['dirty', 'terminal', ['Keep local work', '로컬 작업 남기기'], 3, 'side']
    ],
    edges: [
      ['start', 'targets'], ['targets', 'merged'], ['merged', 'clean', 'yes'],
      ['merged', 'unmerged', 'no'], ['clean', 'remove', 'yes'],
      ['clean', 'dirty', 'no'], ['remove', 'done']
    ]
  }
};

export function flowchartModel(route, language) {
  const ko = language === 'ko';
  const chart = charts[route];
  const labels = ko ? { yes: '예', no: '아니오', retry: '실패한 검사 재실행' }
    : { yes: 'YES', no: 'NO', retry: 'Rerun failed check' };
  const nodes = chart.nodes.map(([id, type, text, row, lane = 'main']) => ({
    id, type, label: text[ko ? 1 : 0], row, lane,
    x: lane === 'main' ? 28 : 78, y: row * 112 + 62,
    width: lane === 'main' ? 42 : 34,
    height: type === 'decision' ? 104 : type === 'terminal' ? 48 : 64
  }));
  return {
    nodes, height: Math.max(...nodes.map(n => n.row)) * 112 + 124,
    edges: chart.edges.map(([from, to, label, kind = 'flow']) => ({
      from, to, label: labels[label] || '', kind
    })),
    legend: ko ? ['시작·종료', '실행', '조건 판단', '단계별 설명']
      : ['Start / end', 'Action', 'Decision', 'Stage details']
  };
}
