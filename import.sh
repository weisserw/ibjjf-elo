#!/bin/bash

output=$(./scripts/pull_bjjcompsystem.py "$@" | tee /dev/tty)
if [ $? -ne 0 ]; then
  echo "Error: ./scripts/pull_bjjcompsystem.py failed"
  exit 1
fi

output_file=$(echo "$output" | grep -oP 'Wrote data to \K.*')
if [ -z "$output_file" ]; then
  echo "Error: Could not extract output filename"
  exit 1
fi

read -p "Press Enter to continue or Ctrl-C to exit..."

./scripts/backup_csv.py "$output_file"
if [ $? -ne 0 ]; then
  echo "Error: ./scripts/backup_csv.py failed"
  exit 1
fi

read -p "Press Enter to continue or Ctrl-C to exit..."

./scripts/load_csv.py "$output_file"
if [ $? -ne 0 ]; then
  echo "Error: ./scripts/load_csv.py failed"
  exit 1
fi

echo "Import ran successfully."