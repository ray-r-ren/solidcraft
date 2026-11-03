#!/bin/bash
set -e
set -euo pipefail
export XDG_RUNTIME_DIR=/tmp/xdg-solve; mkdir -p "$XDG_RUNTIME_DIR" /task/outputs
echo '{"commands":[{"command":"parameters.change","params":{"changes":{"width":"70 mm"}}}]}' > /tmp/w70.json
solidcraft-cli run /tmp/w70.json --in /task/inputs/mount_block.sc --save /task/outputs/mount_block_70.sc \
  --out /task/outputs/mount_block_70.stl > /dev/null
echo "Width changed from 40 to 70 mm; the block is now 70 x 30 x 20 mm." > /task/answer.txt
