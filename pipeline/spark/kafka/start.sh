#!/bin/bash
set -euo pipefail
/opt/kafka/bin/kafka-storage.sh format --ignore-formatted --standalone \
  --cluster-id MkU3OEVBNTcwNTJENDM2Qk --config /opt/pipeline/kafka/node.properties
exec /opt/kafka/bin/kafka-server-start.sh /opt/pipeline/kafka/node.properties
