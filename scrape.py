import requests

for x in range(200):
    response = requests.get(f"http://127.0.0.1:5000/api/matches?gi=true&page={x}")
    print(response.text)
