import json
import os
import random
import time
from datetime import datetime
from kafka import KafkaProducer
from faker import Faker

fake = Faker()

KAFKA_BOOTSTRAP_SERVERS = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
TOPIC_NAME = 'clickstream-events'
EVENT_INTERVAL = float(os.environ.get('EVENT_INTERVAL', '1.0'))

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
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )

    print(f"Starting clickstream event producer for topic: {TOPIC_NAME}")
    print(f"Bootstrap servers: {KAFKA_BOOTSTRAP_SERVERS}")
    print(f"Event interval: {EVENT_INTERVAL}s")

    event_count = 0
    try:
        while True:
            event = generate_clickstream_event()
            producer.send(TOPIC_NAME, value=event)
            event_count += 1
            print(f"[{event_count}] Produced event: {event['event_id']} | type={event['event_type']} | product={event['product_id']} | device={event['device_type']}")
            time.sleep(EVENT_INTERVAL)

    except KeyboardInterrupt:
        print(f"\nStopping producer after {event_count} events...")
    finally:
        producer.close()

if __name__ == "__main__":
    main()
