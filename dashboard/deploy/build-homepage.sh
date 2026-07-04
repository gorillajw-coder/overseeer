#!/usr/bin/env bash
# Homepage(Node.js standalone)를 새로 빌드/재빌드할 때 실행.
# standalone output은 .next/static과 public/을 자동으로 안 넣어주므로 수동 복사 필요.
set -euo pipefail

cd "$(dirname "$0")/.."  # dashboard/

npx --yes pnpm@latest --dir homepage install
npx --yes pnpm@latest --dir homepage build

rm -rf homepage/.next/standalone/.next/static homepage/.next/standalone/public
cp -r homepage/.next/static homepage/.next/standalone/.next/static
cp -r homepage/public homepage/.next/standalone/public

# 우리가 직접 고친 설정 YAML(레포에 커밋되어 있음)을 새로 빌드한 homepage/config/ 위에 덮어씀
cp homepage-config/*.yaml homepage/config/

echo "빌드 완료 → sudo systemctl restart homepage.service 로 반영"
