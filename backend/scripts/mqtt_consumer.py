"""MQTT consumer stub: subscribe to sensor topics and forward events to HTTP ingestion endpoint.

This is a lightweight helper for deployments where devices publish MQTT messages.
"""
import json
import requests

try:
    import paho.mqtt.client as mqtt
except Exception:
    mqtt = None

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
TOPIC = "sensors/#"
INGEST_URL = "http://localhost:8000/iot/ingest"


def on_connect(client, userdata, flags, rc):
    client.subscribe(TOPIC)


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception:
        return
    # forward to ingestion endpoint
    try:
        requests.post(INGEST_URL, json=payload, timeout=5)
    except Exception:
        pass


def main():
    if mqtt is None:
        print("paho-mqtt not installed; install to run MQTT consumer")
        return
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_forever()


if __name__ == "__main__":
    main()
