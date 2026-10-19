"""Build a user-reviewed issue link; never include logs, serials or raw device names."""
from urllib.parse import urlencode

from model import DEVICE_MODELS

ISSUE_BASE = "https://github.com/tylxr59/NagaLibre/issues/new"
ISSUE_TEMPLATE = "device-support.yml"


def device_issue_url(devices=()):
    identities = []
    for device in devices:
        vendor, product = device.get("vendor"), device.get("product")
        if vendor != 0x1532 or type(product) is not int or not 0 <= product <= 0xffff:
            continue
        model = next((m for m in DEVICE_MODELS.values() if product in m["products"]), None)
        name = model["name"] if model else "Unrecognized Razer device"
        identity = f"{name} (1532:{product:04x})"
        priority = 0 if model is None else (2 if model["verified"] else 1)
        entry = (priority, identity)
        if entry not in identities:
            identities.append(entry)
    identities = [identity for _, identity in sorted(identities)]
    params = {"template": ISSUE_TEMPLATE}
    if identities:
        params["model"] = ", ".join(identities[:8])
        params["title"] = "[Device support]: " + identities[0]
    return ISSUE_BASE + "?" + urlencode(params)
