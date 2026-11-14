#!/usr/bin/env bash
# 把上游仓库的更新同步到本 fork。
#
# 用法（在仓库根目录）：
#   bash scripts/sync-upstream.sh            # 只看落后多少，不动任何东西
#   bash scripts/sync-upstream.sh merge      # 把上游合并进当前分支
#   bash scripts/sync-upstream.sh rebase     # 把当前分支变基到上游（历史更干净）
#
# 环境变量：
#   UPSTREAM_REMOTE  上游 remote 名，默认 upstream
#   UPSTREAM_BRANCH  上游分支名，默认 main
#
# 前提：upstream remote 指向原始仓库。没配的话脚本会给出添加命令。
set -euo pipefail

UPSTREAM_REMOTE="${UPSTREAM_REMOTE:-upstream}"
UPSTREAM_BRANCH="${UPSTREAM_BRANCH:-main}"
MODE="${1:-check}"

cd "$(git rev-parse --show-toplevel)"

if ! git remote get-url "$UPSTREAM_REMOTE" >/dev/null 2>&1; then
  cat >&2 <<EOF
没有找到 remote '$UPSTREAM_REMOTE'。先添加原始仓库：
  git remote add upstream https://github.com/rg-ut/uav-inspection.git

确认当前 remote：
  git remote -v
EOF
  exit 2
fi

echo "→ 拉取 $UPSTREAM_REMOTE/$UPSTREAM_BRANCH ..."
git fetch "$UPSTREAM_REMOTE" "$UPSTREAM_BRANCH" --tags --prune

TARGET="$UPSTREAM_REMOTE/$UPSTREAM_BRANCH"
BEHIND=$(git rev-list --count "HEAD..$TARGET")
AHEAD=$(git rev-list --count "$TARGET..HEAD")

echo
echo "当前分支：$(git rev-parse --abbrev-ref HEAD)"
echo "落后上游：$BEHIND 个提交"
echo "领先上游：$AHEAD 个提交（本 fork 的定制）"
echo

if [ "$BEHIND" -gt 0 ]; then
  echo "落后的提交："
  git --no-pager log --oneline --no-decorate "HEAD..$TARGET" | head -20
  echo
fi

case "$MODE" in
  check)
    if [ "$BEHIND" -eq 0 ]; then
      echo "已经是最新。"
    else
      echo "要合并：bash scripts/sync-upstream.sh merge"
      echo "要变基：bash scripts/sync-upstream.sh rebase"
    fi
    ;;
  merge)
    [ "$BEHIND" -eq 0 ] && { echo "已经是最新，无需合并。"; exit 0; }
    git merge --no-ff "$TARGET" -m "chore: 同步上游 $UPSTREAM_BRANCH（$BEHIND 个提交）"
    echo
    echo "合并完成。推送前请先在本机跑一遍："
    echo "  cd app/uav-inspection-ui && npm run build"
    echo "  cd app/uav-inspection-backend && python -m compileall -q ."
    ;;
  rebase)
    [ "$BEHIND" -eq 0 ] && { echo "已经是最新，无需变基。"; exit 0; }
    git rebase "$TARGET"
    echo
    echo "变基完成。若本分支已推送过，需要 git push --force-with-lease。"
    ;;
  *)
    echo "未知模式：$MODE（可选 check / merge / rebase）" >&2
    exit 1
    ;;
esac
