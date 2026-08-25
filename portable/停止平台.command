#!/bin/sh
cd -- "$(dirname -- "$0")" || exit 1
./GeoModelingPlatform.app/Contents/MacOS/GeoModelingPlatform stop
status=$?
if [ "$status" -ne 0 ]; then
  printf '\n停止失败，按回车键关闭窗口。\n'
  read -r _
fi
exit "$status"
