import json
from collections import defaultdict

with open("data/requests.json") as f:
    requests = json.load(f)

print(f"Total requests: {len(requests)}\n")

# Collect all fields and which requests have/lack them
field_presence = defaultdict(list)
field_types = defaultdict(set)

for req in requests:
    for key, val in req.items():
        field_presence[key].append(req["request_id"])
        field_types[key].add(type(val).__name__)

all_fields = set(field_presence.keys())
total = len(requests)

print(f"{'Field':<40} {'Count':>6}  {'Missing':>7}  {'Types'}")
print("-" * 75)
for field in sorted(all_fields):
    count = len(field_presence[field])
    missing = total - count
    types = ", ".join(sorted(field_types[field]))
    flag = " <-- MISSING IN SOME" if missing > 0 else ""
    print(f"{field:<40} {count:>6}  {missing:>7}  {types}{flag}")

# Show requests that are missing fields vs the most common set
print("\n\n--- Requests with missing fields ---")
common_fields = {f for f, ids in field_presence.items() if len(ids) == total}
optional_fields = all_fields - common_fields

if not optional_fields:
    print("All requests have identical field sets. Schema is consistent.")
else:
    print(f"Optional/inconsistent fields: {optional_fields}\n")
    for req in requests:
        missing = all_fields - set(req.keys())
        extra = set(req.keys()) - all_fields  # always empty here, but just in case
        if missing:
            print(f"  {req['request_id']}: missing {missing}")

# Show unique values for key categorical fields
print("\n\n--- Unique values for categorical fields ---")
categorical = ["request_channel", "request_language", "contract_type_requested",
               "status", "scenario_tags", "currency", "unit_of_measure"]
for field in categorical:
    values = set()
    for req in requests:
        v = req.get(field)
        if isinstance(v, list):
            values.update(v)
        elif v is not None:
            values.add(v)
    print(f"  {field}: {sorted(values)}")
