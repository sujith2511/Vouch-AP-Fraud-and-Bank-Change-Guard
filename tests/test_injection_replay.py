import json
from vouch.injection_replay import replay

def test_all_injection_payloads_denied():
    payloads = json.load(open("data/injections.json"))["payloads"]
    rep = replay(payloads)
    assert rep["payloads"] == len(payloads) >= 18
    assert rep["failures"] == [] and rep["state_changing"] == 0
