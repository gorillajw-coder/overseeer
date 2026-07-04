#!/usr/bin/env bash
# Homepage(Node.js standalone)를 새로 빌드/재빌드할 때 실행.
# standalone output은 .next/static과 public/을 자동으로 안 넣어주므로 수동 복사 필요.
set -euo pipefail

cd "$(dirname "$0")/../homepage"

npx --yes pnpm@latest install
npx --yes pnpm@latest build

rm -rf .next/standalone/.next/static .next/standalone/public
cp -r .next/static .next/standalone/.next/static
cp -r public .next/standalone/public

echo "빌드 완료 → sudo systemctl restart homepage.service 로 반영"
