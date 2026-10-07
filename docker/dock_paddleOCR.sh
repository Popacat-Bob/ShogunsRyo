#!/bin/zsh

docker run -it \
  --user root \
  --device /dev/kfd \
  --device /dev/dri \
  --group-add video \
  --ipc=host \
  --security-opt seccomp=unconfined \
  --network host \
  -v ~/Projects/ShogunsRyo:/workspace \
  -w /workspace \
  -e HSA_OVERRIDE_GFX_VERSION=10.3.0 \
  ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-vl:latest-amd-gpu \
  /bin/bash
