#!/usr/bin/env bash
# Build script for Render
set -o errexit

pip install --upgrade pip
pip install setuptools wheel
pip install -r requirements.txt