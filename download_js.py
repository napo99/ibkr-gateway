import requests

url = "https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"
response = requests.get(url)

if response.status_code == 200:
    with open("lightweight-charts.standalone.production.js", "wb") as f:
        f.write(response.content)
    print("Successfully downloaded lightweight-charts.standalone.production.js")
else:
    print(f"Failed to download. Status code: {response.status_code}")
