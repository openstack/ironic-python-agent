#!/bin/bash
#
# Cleans up docker images and containers

containers=$(docker ps -a -q)
images=$(docker images -q)

# All the docker commands followed by || true because occasionally docker
# will fail to remove an image or container, & I want make to keep going anyway
if [[ ! -z "$containers" ]]; then
  docker rm $containers || true
fi 

if [[ ! -z "$images" ]]; then
  docker rmi $images || true
fi
