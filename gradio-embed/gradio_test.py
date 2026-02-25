from gradio_client import Client

client = Client("MoeAkin/PSE-Bot")
result = client.predict(
    "Hello!!",  # positional argument for the first input
    api_name="/run/predict"  # use /run/predict, not //predict or /predict
)
print(result)