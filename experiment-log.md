
## 2026-03-17: e013 시작
- **목표**: Score Pipeline Bug Fix + 듀얼 스코어링 통합
- **Issue**: #13
- **Status**: started
- **비평 근거**: 인터랙티브 리포트의 모든 relevance score가 0점 — 스냅샷 저장이 스코어링 전에 발생, 듀얼 스코어링 시스템 혼란

## 2026-03-17: e014 시작
- **목표**: 스코어링 알고리즘 재설계 (변별력 확보)
- **Issue**: #14
- **Status**: started
- **비평 근거**: 점수 분포 0.01~0.30에 압축 (max=0.30), 42개 키워드 부족, "AI" false positive, amount_bonus 무조건 가산

## 2026-03-17: e015 시작
- **목표**: 연구자 프로필 기반 개인화 시스템
- **Issue**: #15
- **Status**: started
- **비평 근거**: 모든 연구자에게 동일 898건 목록 제공, IPK 내 다양한 연구 프로필 미반영

## 2026-03-17: e016 시작
- **목표**: MECE 계층 분류 + 인터랙티브 리포트 재설계
- **Issue**: #16
- **Status**: started
- **비평 근거**: 898건 flat card grid → 인지 과부하, 분류 축/우선순위 계층 부재

## 2026-03-19: e046 concluded (NO-GO)
- **결과**: CARB-X NO-GO (1-2건/년, 이전 삭제 이력). JPIAMR NO-GO (한국 비회원국).
- **Issue**: #33

## 2026-03-19: e052 시작
- **목표**: Cron 이메일 PATH 수정 + pipeline stderr 로깅
- **Issue**: #34
- **Milestone**: v2.5 - 품질 강화 + 모니터링
- **Status**: started
- **비평 근거**: 3일간 cron 이메일 전송 0%. $HOME/bin PATH 미포함 + stderr만 로깅

## 2026-03-19: e053 시작
- **목표**: 모니터링 테스트 격리 (tmp_path) + run_history 재리셋
- **Issue**: #35
- **Milestone**: v2.5 - 품질 강화 + 모니터링
- **Status**: started
- **비평 근거**: 92% 테스트 오염, e049 리셋 불완전 (근본 원인 미수정)

## 2026-03-19: e054 시작
- **목표**: 플러그인 스킬 문서 정정 + deadlines eligibility 추가
- **Issue**: #36
- **Milestone**: v2.5 - 품질 강화 + 모니터링
- **Status**: started
- **비평 근거**: setup 스킬 PyPI 설치 명령 오류, collect 8소스→실제 3소스, deadlines eligibility 누락
