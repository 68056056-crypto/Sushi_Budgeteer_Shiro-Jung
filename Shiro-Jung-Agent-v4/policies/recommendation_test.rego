package shiro_test
import rego.v1
import data.shiro

line := {"quantity":1,"catalog_item":true,"food":true,"unit_cents":4000,
    "reported_unit_cents":4000,"reported_subtotal_cents":4000,
    "allergen_blocked":false,"hard_excluded":false,"only_allowed":true,"evidence_confirmed":false}
facts := {"schema_version":1,"lines":[line],"python_issues":[],"total_cents":4000,"food_cents":4000,
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
    altered := object.union(facts,{"allergy_requested":true})
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
