#!/bin/sh

if [ "$1" = "--check" ]; then
    find . -name node_modules -prune -o -name '*.py' | xargs black --check
else
    find . -name node_modules -prune -o -name '*.py' | xargs black
fi