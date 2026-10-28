"""Source-safety guards for the lab setup (pure helpers, no B2 I/O)."""
from b2_setup import bucket_rules_known, existing_rules_intact, lab_prefix_ok


def test_lab_prefix_key_must_stay_inside_lab():
    assert lab_prefix_ok({"namePrefix": "lab/"})
    assert lab_prefix_ok({"namePrefix": "lab/2026/"})
    assert not lab_prefix_ok({})
    assert not lab_prefix_ok({"namePrefix": None})
    assert not lab_prefix_ok({"namePrefix": ""})
    assert not lab_prefix_ok({"namePrefix": "inbox/"})
    assert not lab_prefix_ok({"namePrefix": "la"})


def test_bucket_update_refuses_foreign_or_unknown_rules():
    lab = {"corsRuleName": "sessionLabBrowser", "allowedOrigins": ["http://x"]}
    life = {"fileNamePrefix": "lab/"}
    assert existing_rules_intact({}, [lab], [life])
    assert existing_rules_intact({"corsRules": [lab], "lifecycleRules": [life]}, [lab], [life])
    prod = dict(lab, allowedOrigins=["https://prod.example"])
    assert not existing_rules_intact(
        {"corsRules": [prod], "lifecycleRules": []}, [lab], [life])
    assert not existing_rules_intact(
        {"corsRules": [{"corsRuleName": "prodPlayback"}], "lifecycleRules": []}, [lab], [life])
    assert not existing_rules_intact(
        {"corsRules": [], "lifecycleRules": [{"fileNamePrefix": "inbox/"}]}, [lab], [life])
    assert bucket_rules_known({"corsRules": [], "lifecycleRules": []})
    assert not bucket_rules_known({})
