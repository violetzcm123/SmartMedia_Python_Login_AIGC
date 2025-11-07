import requests, json

url = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
headers = {
    "Content-Type": "application/json",
    "Authorization": "Bearer 9dc3adae-b246-4135-b7fd-ea15fb3f8ff0"  # ← 这里换成你自己的 API key
}
data = {
    "model": "doubao-seedream-4-0-250828",
    "prompt": "鱼眼镜头，一只猫咪的头部",
    "size": "1024x1024",
    "response_format": "url"
}
resp = requests.post(url, headers=headers, json=data)
print(resp.status_code)
print(resp.text)
