package shiro_test
import rego.v1
import data.shiro

line := {"allergen_tags":[],"allergen_status":"unknown","dietary_tags":[],"dietary_status":"reviewed_dataset","quantity":1,"catalog_item":true,"food":true,"unit_cents":4000,
    "reported_unit_cents":4000,"reported_subtotal_cents":4000,
    "allergen_blocked":false,"hard_excluded":false,"only_allowed":true,"evidence_confirmed":false}
facts := {"schema_version":2,"user_allergens":[],"excluded_dietary_tags":[],"lines":[line],"python_issues":[],"total_cents":4000,"food_cents":4000,
    "budget_cents":10000,"count":1,"food_count":1,"min_items":1,"max_items":20,
    "data_mode":"strict","separate_budget":false,"allergy_requested":false,
    "catalog_revision":"abc","result_catalog_revision":"abc"}

test_allow_valid if { shiro.allow with input as facts }
test_deny_missing_input if { not shiro.allow with input as {} }
test_deny_missing_line_schema if {
    altered := object.union(facts,{"lines":[{}]})
    not shiro.allow with input as altered
}
test_deny_over_budget_independently if {
    altered := object.union(facts,{"budget_cents":1000})
    result := shiro.decision with input as altered
    not result.allow
    "over_budget" in result.deny_reasons
}
test_deny_allergen_independently if {
    altered := object.union(facts,{"lines":[object.union(line,{"allergen_blocked":true})]})
    result := shiro.decision with input as altered
    "allergen_conflict" in result.deny_reasons
}
test_deny_strict_unknown_evidence if {
    altered := object.union(facts,{"allergy_requested":true,"user_allergens":["egg"]})
    not shiro.allow with input as altered
}
test_simulation_still_enforces_allergen if {
    altered := object.union(facts,{"data_mode":"simulation","allergy_requested":true,
        "lines":[object.union(line,{"allergen_blocked":true})]})
    not shiro.allow with input as altered
}
test_allow_simulation_unknown_only if {
    altered := object.union(facts,{"data_mode":"simulation","allergy_requested":true})
    shiro.allow with input as altered
}
test_deny_hard_exclusion if {
    altered := object.union(facts,{"lines":[object.union(line,{"hard_excluded":true})]})
    not shiro.allow with input as altered
}
test_deny_price_tampering if {
    altered := object.union(facts,{"lines":[object.union(line,{"reported_unit_cents":1})]})
    not shiro.allow with input as altered
}
test_deny_subtotal_tampering if {
    altered := object.union(facts,{"lines":[object.union(line,{"reported_subtotal_cents":1})]})
    not shiro.allow with input as altered
}
test_deny_revision_changed if {
    altered := object.union(facts,{"result_catalog_revision":"old"})
    not shiro.allow with input as altered
}
test_deny_count_mismatch if {
    altered := object.union(facts,{"count":2})
    not shiro.allow with input as altered
}
test_deny_food_required if {
    altered := object.union(facts,{"food_count":0})
    not shiro.allow with input as altered
}
test_deny_python_issues if {
    altered := object.union(facts,{"python_issues":["fixed choice mismatch"]})
    not shiro.allow with input as altered
}

test_checkout_expanded_count_bound if {
    altered := object.union(facts,{"checkout":true,"max_items":180,"drinks_count":0,"desserts_count":0})
    shiro.allow with input as altered
}
test_normal_flow_cannot_expand_count_bound if {
    altered := object.union(facts,{"max_items":180})
    result := shiro.decision with input as altered
    "invalid_count_limits" in result.deny_reasons
}
test_checkout_keeps_food_cap if {
    altered := object.union(facts,{"checkout":true,"max_items":180,"food_count":61})
    result := shiro.decision with input as altered
    "checkout_food_limit" in result.deny_reasons
}
test_checkout_keeps_extra_category_cap if {
    altered := object.union(facts,{"checkout":true,"max_items":180,"drinks_count":61,"desserts_count":0})
    result := shiro.decision with input as altered
    "checkout_drinks_limit" in result.deny_reasons
}

test_checkout_requires_category_counts if {
    altered := object.union(facts,{"checkout":true,"max_items":180})
    not shiro.allow with input as altered
}

test_raw_allergen_denied_when_python_flags_false if {
    altered := object.union(facts,{"user_allergens":["egg"],"data_mode":"simulation",
        "lines":[object.union(line,{"allergen_tags":["egg"],"allergen_blocked":false})]})
    result := shiro.decision with input as altered
    "allergen_conflict" in result.deny_reasons
}
test_seafood_expands_in_rego_to_echinoderm if {
    altered := object.union(facts,{"user_allergens":["seafood"],"data_mode":"simulation",
        "lines":[object.union(line,{"allergen_tags":["echinoderm"]})]})
    result := shiro.decision with input as altered
    "allergen_conflict" in result.deny_reasons
}
test_raw_dietary_denied_when_python_flags_false if {
    altered := object.union(facts,{"excluded_dietary_tags":["raw"],
        "lines":[object.union(line,{"dietary_tags":["raw"],"hard_excluded":false})]})
    result := shiro.decision with input as altered
    "hard_exclusion" in result.deny_reasons
}
test_raw_unknown_evidence_denied_when_boolean_claims_confirmed if {
    altered := object.union(facts,{"user_allergens":["egg"],
        "lines":[object.union(line,{"evidence_confirmed":true})]})
    result := shiro.decision with input as altered
    "unknown_allergen_evidence" in result.deny_reasons
}
