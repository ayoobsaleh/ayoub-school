#!/usr/bin/env bash
# يبني static/app.css من الأصناف المستخدمة في static/index.html (بدلاً من مكتبة Tailwind في المتصفح).
# التشغيل: bash tools/build_css.sh   (يُنزّل أداة Tailwind المستقلة مرة واحدة إن لم تكن موجودة)
set -euo pipefail
cd "$(dirname "$0")/.."
TW="${TAILWIND_BIN:-.cache/tailwindcss}"
if [ ! -x "$TW" ]; then
  mkdir -p .cache
  curl -sSL -o "$TW" https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-linux-x64
  chmod +x "$TW"
fi
printf '@tailwind base;\n@tailwind components;\n@tailwind utilities;\n' > .cache/in.css
"$TW" -c tailwind.config.js -i .cache/in.css -o static/app.css --minify
echo "static/app.css: $(wc -c < static/app.css) bytes"
