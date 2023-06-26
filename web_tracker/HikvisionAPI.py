import base64
import hashlib
import hmac
import json
import time

import requests
import urllib3

# 禁用警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class HikvisionAPI:
    def __init__(self, uapi, appKey, appSecret, headers_url, data):
        self.uapi = uapi
        self.data = data
        self.appKey = appKey
        self.appSecret = appSecret
        self.t_new = None
        self.signature = None
        self.headers_url = headers_url

    def load_config(self):
        self.t_new = time.strftime('%Y-%m-%dT%H:%M:%S+08:00', time.localtime(time.time()))

    def sign(self, key, value):
        temp = hmac.new(key.encode(), value.encode(), digestmod=hashlib.sha256)
        return base64.b64encode(temp.digest()).decode()

    def get_headers(self):
        httpHeaders = 'POST' + '\n' + '*/*' + '\n' + 'application/json' + '\n' + str(self.t_new) + '\n'
        customHeaders = "x-ca-key" + ":" + self.appKey + "\n"
        url = r'' + self.headers_url
        sign_str = httpHeaders + customHeaders + url
        self.signature = self.sign(self.appSecret, sign_str)
        headers = {
            'Accept': '*/*',
            'Content-Type': 'application/json',
            'Date': self.t_new,
            'X-Ca-Signature-Headers': 'x-ca-key',
            'X-Ca-Key': self.appKey,
            'X-Ca-Signature': self.signature,
        }
        return headers

    def request(self):
        self.load_config()
        headers = self.get_headers()
        uri = self.uapi
        print(uri, headers, self.data)
        response = requests.post('https://'+uri + self.headers_url, data=json.dumps(self.data), headers=headers, verify=False)
        return json.loads(response.text)
