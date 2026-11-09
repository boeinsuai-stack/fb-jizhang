#!/usr/bin/env bash
# 一键跑全套测试。用法：tests/run_all.sh [旧 fixture.json] [v2 种子.json]
# 不给 fixture 只跑三套不需要真实数据的（跟 GitHub 上自动跑的一样）；真实数据放仓库外面，不要提交
# Chrome 不在 /usr/bin/google-chrome 时：CHROME=/path/to/chrome tests/run_all.sh ...
set -u
cd "$(dirname "$0")/.."
F="${1:-}"; S="${2:-}"; fail=0
run() { echo "== $*"; if "$@" > /tmp/fbjz-test.log 2>&1; then tail -1 /tmp/fbjz-test.log; else grep "❌" /tmp/fbjz-test.log; tail -3 /tmp/fbjz-test.log; fail=1; fi; }
run python3 tests/test_offline_resv.py
run python3 tests/test_sync.py
run python3 tests/test_realsdk.py
if [ -n "$F" ]; then
  [ -n "$S" ] || { S=$(mktemp --suffix=.json); node tests/v2_seed.js "$F" "$S" > /dev/null; }
  run node tests/v2_roundtrip.js "$F"
  run python3 tests/test_v2_diff.py "$F" "$S"
  run python3 tests/test_v2_migrate.py "$F"
  run python3 tests/test_v2_relay.py "$F" "$S"
  run node tests/v2_fuzz.js "$F" 500 3
fi
[ $fail = 0 ] && echo "全部通过" || { echo "有没通过的"; exit 1; }
