#!/bin/sh
cd -- "$(dirname -- "$0")" || exit 1
./GeoModelingPlatform start
status=$?
if [ "$status" -ne 0 ]; then
  printf '\n启动失败，按回车键关闭窗口。\n'
  read -r _
fi
exit "$status"
