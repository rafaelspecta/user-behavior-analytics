import json
import random
import time
from datetime import datetime
from kafka import KafkaProducer
from faker import Faker

# Initialize Faker for generating realistic data
fake = Faker()

# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS = 'localhost:9092'
TOPIC_NAME = 'clickstream-events'

def generate_clickstream_event():
    """Generate a synthetic clickstream event."""
    event_types = ['page_view', 'product_view', 'add_to_cart', 'checkout', 'purchase']
    products = ['laptop', 'smartphone', 'headphones', 'tablet', 'smartwatch']
    
    return {
        'event_id': fake.uuid4(),
        'user_id': fake.uuid4(),
        'session_id': fake.uuid4(),
        'event_type': random.choice(event_types),
        'product_id': random.choice(products),
        'timestamp': datetime.utcnow().isoformat(),
        'page_url': fake.url(),
        'user_agent': fake.user_agent(),
        'ip_address': fake.ipv4(),
        'device_type': random.choice(['mobile', 'desktop', 'tablet']),
        'browser': fake.chrome(),
        'os': random.choice(['Windows', 'macOS', 'Linux', 'iOS', 'Android']),
        'country': fake.country_code(),
        'referrer': fake.url(),
        'screen_resolution': f"{random.randint(800, 3840)}x{random.randint(600, 2160)}",
        'time_on_page': random.randint(1, 300),
        'scroll_depth': random.randint(0, 100),
        'click_coordinates': {
            'x': random.randint(0, 1920),
            'y': random.randint(0, 1080)
        }
    }

def main():
    # Initialize Kafka producer
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )
    
    print(f"Starting clickstream event producer for topic: {TOPIC_NAME}")
    
    try:
        while True:
            # Generate and send events
            event = generate_clickstream_event()
            producer.send(TOPIC_NAME, value=event)
            
            # Print every 1000th event for monitoring
            if int(event['event_id'].split('-')[0], 16) % 1000 == 0:
                print(f"Produced event: {event['event_id']}")
            
            # Simulate realistic event rate (approximately 5M events per day)
            time.sleep(random.uniform(0.01, 0.05))
            
    except KeyboardInterrupt:
        print("\nStopping producer...")
    finally:
        producer.close()

if __name__ == "__main__":
    main() 