#!/bin/bash
echo "Creating Kafka topics..."

kafka-topics --create \
  --topic clickstream-events \
  --partitions 3 \
  --replication-factor 1 \
  --if-not-exists \
  --bootstrap-server kafka:29092

kafka-topics --create \
  --topic clickstream-errors \
  --partitions 1 \
  --replication-factor 1 \
  --if-not-exists \
  --bootstrap-server kafka:29092

echo "Listing Kafka topics..."
kafka-topics --list --bootstrap-server kafka:29092

echo "Kafka topic initialization complete!"
