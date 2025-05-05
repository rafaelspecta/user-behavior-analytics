#!/bin/bash

# Start Zookeeper
echo "Starting Zookeeper..."
docker-compose up -d zookeeper

# Wait for Zookeeper to be ready
echo "Waiting for Zookeeper to be ready..."
sleep 10

# Start Kafka
echo "Starting Kafka..."
docker-compose up -d kafka

# Wait for Kafka to be ready
echo "Waiting for Kafka to be ready..."
sleep 10

# Create Kafka topics
echo "Creating Kafka topics..."
docker-compose exec kafka kafka-topics --create --topic clickstream-events --partitions 3 --replication-factor 1 --if-not-exists --bootstrap-server localhost:9092
docker-compose exec kafka kafka-topics --create --topic clickstream-errors --partitions 1 --replication-factor 1 --if-not-exists --bootstrap-server localhost:9092

# List topics
echo "Listing Kafka topics..."
docker-compose exec kafka kafka-topics --list --bootstrap-server localhost:9092

echo "Kafka setup complete!" 