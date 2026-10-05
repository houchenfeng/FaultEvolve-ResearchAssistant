#!/bin/bash
# Run mock evolution for testing

set -e

TASK_DIR="${1:-benchmark/hdd_mvp}"
ITERATIONS="${2:-3}"

echo "Running mock evolution on $TASK_DIR..."
fe evolve local "$TASK_DIR" --mock --iterations "$ITERATIONS" --json
