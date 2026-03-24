#!/bin/bash

for i in $(seq 1 50); do
    if curl -sf http://127.0.0.1:8888/api/status > /dev/null 2>&1; then
        echo "Jupyter Server is ready"
        exit 0
    fi
    sleep 0.2
done

echo "Jupyter Server failed to start within 10s"
exit 1
