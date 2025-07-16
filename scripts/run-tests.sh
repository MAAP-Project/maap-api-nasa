#!/bin/bash
set -e

echo "Starting MAAP API Test Suite..."

# Navigate to docker directory
cd "$(dirname "$0")/../docker"

# Build test images
echo "Building test images..."
docker-compose -f docker-compose-test.yml build

# Run tests with coverage
echo "Running tests..."
docker-compose -f docker-compose-test.yml run --rm test

# Display results
echo "Test execution completed. Results available in docker/test-results/"

# Cleanup
docker-compose -f docker-compose-test.yml down -v