"""Source-safety guards for the lab setup (pure helpers, no B2 I/O)."""
from b2_setup import bucket_rules_known, existing_rules_intact, lab_prefix_ok

LAB_CORS = [{"corsRuleName": "sessionLabBrowser"}]
LAB_LIFE = [{"fileNamePrefix": "lab/"}]


def test_lab_prefix_key_must_stay_inside_lab():
    assert lab_prefix_ok({"namePrefix": "lab/"})
    assert lab_prefix_ok({"namePrefix": "lab/2026/"})
    assert not lab_prefix_ok({})
    assert not lab_prefix_ok({"namePrefix": None})
    assert not lab_prefix_ok({"namePrefix": ""})
    assert not lab_prefix_ok({"namePrefix": "inbox/"})
    assert not lab_prefix_ok({"namePrefix": "la"})


def test_bucket_update_refuses_foreign_or_unknown_rules():
    assert existing_rules_intact({}, LAB_CORS, LAB_LIFE)
    assert existing_rules_intact({"corsRules": LAB_CORS, "lifecycleRules": LAB_LIFE}, LAB_CORS, LAB_LIFE)
    assert not existing_rules_intact(
        {"corsRules": [{"corsRuleName": "prodPlayback"}], "lifecycleRules": []}, LAB_CORS, LAB_LIFE)
    assert not existing_rules_intact(
        {"corsRules": [], "lifecycleRules": [{"fileNamePrefix": "inbox/"}]}, LAB_CORS, LAB_LIFE)
    assert bucket_rules_known({"corsRules": [], "lifecycleRules": []})
    assert not bucket_rules_known({})
