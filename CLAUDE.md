# 2026-summer-ubd

수원성교회 유바디교구 2마을 저장소. 두 가지가 들어 있다.

- 루트(`app.py`, `templates/`, `static/`, `zone_survey/`): 여름 선교 소통방 Flask 앱 (README.md 참고)
- `apps_script/zone_survey/`: **구역편성 설문** Google Apps Script. 지금 주로 개발하는 곳

## 구역편성 설문 (apps_script/zone_survey)

구글시트 `2026 유바디교구 구역편성_20260315`(ID `1dz9ZnTtlAuj-fglzLSnh5ndF9A_-F-3OIjSRw25jtGw`)에 붙어 있는 스크립트.
구역장이 카톡 링크(웹앱 `?z=토큰`)로 가정별 정보를 확인·작성하면 시트에 바로 저장된다. 자세한 사용법은 `apps_script/zone_survey/README.md`.

| 파일 | 내용 |
|---|---|
| `Code.gs` | 시트 메뉴, 웹앱 진입점, 저장 API, `FAMILY_FIELDS`(가정 시트 열 순서) |
| `Parser.gs` | 원본 `2025 구역편성(0905)` 시트 파서 |
| `Attendance.gs` | 25·26년 출석 기록을 읽어 `25년 출석률`·`26년 출석률` 칸 채우기 |
| `Leader.html` / `Messages.html` | 구역장 화면 / 카톡 메시지 복사 창 |
| `deploy.sh` | `clasp push` + 웹앱 배포 갱신 (배포 ID `.deployment_id`, 링크 주소 유지) |
| `tools/zone_draft.py` | 확정 구역장 기준 구역편성 초안 계산 (시트 밖에서 돌리는 도구) |

### 배포
- **main에 머지되면 GitHub Actions(`.github/workflows/deploy-zone-survey.yml`)가 자동으로 배포**한다. 저장소 시크릿 `CLASPRC_JSON`(clasp 로그인 정보)이 필요하다.
- 작업은 브랜치 → PR → main 머지 순서로 한다. 클라우드 세션에서는 clasp 로그인 정보가 없으니 직접 `deploy.sh`를 돌리지 말고 PR로 올린다.
- 집/회사 Mac에서는 `.claude/settings.local.json` 훅이 수정할 때마다 `clasp push` 하고 턴이 끝나면 `deploy.sh`를 돌린다 (git에 올리지 않는 로컬 설정).
- `.clasp.json`(스크립트 ID)과 `.deployment_id`는 지우거나 바꾸지 않는다. 바뀌면 구역장 링크가 모두 달라진다.
- 새 `.gs`/`.html` 파일을 만들면 `.claspignore` 화이트리스트에 추가해야 올라간다.

### 지켜야 할 것
- 구역장들이 이미 작성한 데이터가 시트에 있다. `FAMILY_FIELDS` 순서를 바꾸면 기존 행과 열이 어긋나므로, 열을 추가할 때는 `ensureFamilyColumns_()`처럼 기존 시트에 열을 끼워 넣는 이전 코드를 같이 둔다.
- `구분 = 사랑구역`(원본 87행 아래) 가정은 구역과 무관한 명단이라 구역장 화면·구역 집계·결과 시트에서 뺀다 (`LOVE_ZONE_ROLE`).
- 웹앱에서 부를 수 있는 함수는 이름 끝에 `_`가 없는 전역 함수뿐이다. 관리자 함수는 `requireSheetUi_()`로 시트 메뉴에서만 돌게 한다.
- 시트에 개인정보(이름·연락처·자녀)가 있다. 데이터를 저장소에 커밋하지 않는다.
- 문서와 사용자 안내 문구는 한국어로 쓴다.

### 구역편성 초안 (2027)
- 시트 탭 `2027 구역편성(1안)`: 확정 구역장 7가정(김상단, 신상혁, 김용현, 조민규, 홍진기, 박진성, 전두표) 기준 1안. A열 `새 구역`, B열 `역할`, C열 `ID`만 직접 값이고 나머지는 `구역편성_가정`에서 ID로 찾아오는 수식이라, 가정을 옮기려면 A열만 바꾸면 위쪽 집계가 따라 바뀐다.
- 새 안을 만들 때: `구역편성_가정` 시트 값을 JSON으로 받아 `python3 apps_script/zone_survey/tools/zone_draft.py 가정.json --leaders ...` 로 계산하고, 같은 형식의 새 탭(`2027 구역편성(2안)` 등)으로 쓴다. 같이 배정 요청 묶음은 스크립트의 `GROUPS`.
- 1마을에서 올라올 가정은 아직 시트에 없다. 명단이 오면 추가해야 한다.
