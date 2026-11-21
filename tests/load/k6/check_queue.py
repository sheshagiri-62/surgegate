"""After a waiting-room load test: check the queue in DynamoDB.

    python check_queue.py <event-id>

Prints: places, positions 1..N unique without gaps, admitted count, how early arrivals were
spread (shuffle), and admissions per minute (must not exceed the admission rate).
"""

import sys
from collections import Counter
from datetime import datetime

import boto3
from boto3.dynamodb.conditions import Key

event_id = sys.argv[1]
table = boto3.resource("dynamodb", region_name="ap-south-1").Table("surgegate-dev-queue")
items, kwargs = [], {"KeyConditionExpression": Key("PK").eq(f"EVENT#{event_id}")}
while True:
    page = table.query(**kwargs)
    items += page["Items"]
    if "LastEvaluatedKey" not in page:
        break
    kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

meta = next(i for i in items if i["SK"] == "META")
places = [i for i in items if i["SK"].startswith("USER#")]
positions = sorted(int(p["position"]) for p in places if "position" in p)
start = datetime.fromisoformat(meta["sale_starts_at"])
early = sorted(
    (p for p in places if datetime.fromisoformat(p["joined_at"]) < start and "position" in p),
    key=lambda p: p["joined_at"],
)
first_ten = [int(p["position"]) for p in early[:10]]
per_minute = Counter(
    datetime.fromisoformat(p["admitted_at"]).strftime("%H:%M") for p in places if "admitted_at" in p
)
status, rate, serving = meta["status"], meta["admission_rate"], meta["serving_up_to"]
print(f"queue status={status} rate={rate}/min serving={serving}")
print(
    f"places={len(places)} numbered={len(positions)} "
    f"unique_without_gaps={positions == list(range(1, len(positions) + 1))}"
)
print(f"admitted (pass issued)={sum('admitted_at' in p for p in places)}")
print(f"joined before the start={len(early)}; positions of the 10 earliest arrivals={first_ten}")
print("admitted per minute:", dict(sorted(per_minute.items())))
