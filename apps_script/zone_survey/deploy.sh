#!/bin/bash
# 구역편성 설문 Apps Script를 구글시트에 올리고 웹앱으로 배포한다.
#   처음: 시트에 연결된 스크립트를 만들고 웹앱 배포 → 주소를 Deployment.gs에 적는다
#   이후: 코드만 올리고 같은 배포를 새 버전으로 바꾼다 (구역장 링크 주소는 그대로)
# 필요: clasp 로그인(clasp login), https://script.google.com/home/usersettings 에서 Apps Script API 사용
set -euo pipefail
cd "$(dirname "$0")"

SHEET_ID=1dz9ZnTtlAuj-fglzLSnh5ndF9A_-F-3OIjSRw25jtGw
TITLE='구역편성 설문'

if [ ! -f .clasp.json ]; then
  # 빈 폴더에서 만들어야 기본 파일이 이 폴더의 코드를 덮어쓰지 않는다
  tmp=$(mktemp -d)
  (cd "$tmp" && clasp create-script --title "$TITLE" --parentId "$SHEET_ID" --rootDir .)
  sed 's#"rootDir": *"[^"]*"#"rootDir": "."#' "$tmp/.clasp.json" > .clasp.json
  rm -rf "$tmp"
  echo "시트에 연결된 스크립트를 만들었습니다."
fi

write_url() {
  printf '// deploy.sh가 자동으로 만드는 파일입니다. 직접 고치지 마세요.\nvar DEPLOYED_WEBAPP_URL = %s;\n' "$1" > Deployment.gs
}

if [ ! -s .deployment_id ]; then
  [ -f Deployment.gs ] || write_url "''"
  clasp push -f
  out=$(clasp create-deployment -d "$TITLE")
  echo "$out"
  id=$(echo "$out" | grep -o 'AKfy[A-Za-z0-9_-]*' | head -1)
  [ -n "$id" ] || { echo "배포 ID를 찾지 못했습니다." >&2; exit 1; }
  echo "$id" > .deployment_id
fi

id=$(cat .deployment_id)
write_url "'https://script.google.com/macros/s/$id/exec'"
clasp push -f
clasp update-deployment "$id" -d "$TITLE $(date '+%Y-%m-%d %H:%M')"
echo
echo "웹앱 주소: https://script.google.com/macros/s/$id/exec"
