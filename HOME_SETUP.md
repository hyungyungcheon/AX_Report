# 집 PC에서 이 프로젝트 받기

> 2026-07-09, 사무실에서 작업하던 중 Claude가 안내한 내용을 메모로 남깁니다.

## 처음이라면 → pull이 아니라 clone

pull은 "이미 받아둔 저장소를 최신으로 갱신"하는 명령이라, 아무것도 없는 상태에서는 먼저 통째로 복제(clone)해야 합니다:

```powershell
git clone https://github.com/hyungyungcheon/AX_Report.git
```

원하는 폴더에서 위 한 줄만 실행하면 전체 프로젝트(코드 + 지금까지 만든 리포트)가 그대로 내려옵니다. 집에서 Claude Code를 쓴다면 그냥 **"https://github.com/hyungyungcheon/AX_Report.git 클론해줘"** 라고 말해도 됩니다.

## 그다음부터는 pull

사무실에서 리포트를 더 만들어 푸시한 뒤, 집에서 최신본을 받을 때는 그 폴더에서:

```powershell
git pull
```

(또는 Claude Code에게 "pull 해줘") 하면 됩니다. 반대로 집에서 작업한 걸 사무실로 가져올 때도 푸시 → 풀 순서로 똑같이 하면 됩니다.

## 집 PC에서 필요한 것

- **리포트 조회만** 할 거라면 아무것도 필요 없습니다. `site/index.html`을 브라우저로 열면 됩니다.
- **새 리포트 생성까지** 하려면 Python과 Claude Code(로그인 포함)가 설치되어 있어야 `AX리포트_시작.bat`이 동작합니다.

## 주의

양쪽 PC에서 **동시에 작업하고 푸시하면 충돌**이 날 수 있으니, 자리를 옮기기 전에 푸시하고, 앉자마자 풀 받는 습관만 들이면 문제없습니다.
