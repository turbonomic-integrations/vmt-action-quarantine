#!/usr/bin/env bash
VERSION=1.0.0
source clean.sh
cp ../README.md ../build/
cp ../README.pdf ../build/
cp ../src/kube/deployment.yaml ../build/
cp ../resources/config.yaml ../build/
cp ../resources/manifest.json ../build/

docker build --no-cache -f ../src/docker/Dockerfile -t vmt-action-quarantine:$VERSION ../
docker save vmt-action-quarantine:$VERSION > ../build/docker-vmt-action-quarantine-$VERSION.tar

zip -j ../build/vmt-action-quarantine-$VERSION.zip ../build/*
