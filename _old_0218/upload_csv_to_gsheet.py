import csv
import json
import requests

# Webhook URL（GASでデプロイしたURL）
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbyg1dMZEouYwtv8X8z_w7V3mnkryqPaJwOEiwObJ6Xb6lMg6rlvEODUp1ZSOQrPry0K/exec"

# CSVファイルのパス
CSV_FILE = r"C:\Users\furuie\Dropbox\006_TRADE\historycal\entrypoint.csv"

# CSVを読み込んでデータをリスト化
def read_csv(file_path):
    data = []
    with open(file_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)
    return data

# WebhookにPOST送信
def send_to_webhook(data):
    headers = {"Content-Type": "application/json"}
    response = requests.post(WEBHOOK_URL, data=json.dumps(data), headers=headers)
    print("Response:", response.text)

# 実行
csv_data = read_csv(CSV_FILE)
send_to_webhook(csv_data)
