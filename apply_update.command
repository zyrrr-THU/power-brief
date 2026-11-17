#!/bin/bash
# PowerBrief 2.1.0 更新包：把 files/ 里的文件复制到当前所在的 power-brief 仓库文件夹。
# 用法（在 Mac 终端）：先 cd 到 power-brief 仓库文件夹，再 bash 本文件路径
PACK="$(cd "$(dirname "$0")" && pwd)"
TARGET="$(pwd)"

if [ ! -d "$TARGET/.git" ] || [ ! -d "$TARGET/powerbrief" ]; then
  echo "当前文件夹不是 power-brief 仓库：$TARGET"
  echo "请先 cd 到 power-brief 文件夹（里面有 powerbrief、docs 和 .github），再运行本脚本。"
  exit 1
fi

echo "复制到：$TARGET"
n=0
while IFS= read -r f; do
  [ -z "$f" ] && continue
  mkdir -p "$TARGET/$(dirname "$f")"
  cp "$PACK/files/$f" "$TARGET/$f" && echo "  已更新 $f" && n=$((n+1))
done < "$PACK/文件清单.txt"
echo "完成：共 $n 个文件。当前版本：$(cat "$TARGET/VERSION")"
echo "下一步：git add -A && git commit -m \"v2.1.0\" && git push"
