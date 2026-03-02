#!/bin/bash
set -e

echo "Building Krill Docker container..."
docker build -t krill:latest .
echo "Build complete."
