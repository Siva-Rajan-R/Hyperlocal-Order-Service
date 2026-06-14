import urllib.request
import json

try:
    req = urllib.request.Request('http://localhost:8002/api/v1/orders/stats/customer/TEST-SHOP/c8a1d26e-5f09-5951-bfea-fbf43ca65a45')
    with urllib.request.urlopen(req) as response:
        print(response.read().decode('utf-8'))
except urllib.error.URLError as e:
    print(e.reason)
