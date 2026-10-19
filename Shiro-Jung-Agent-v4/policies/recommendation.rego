package shiro
import rego.v1

policy_version := "shiro-4.0"
default allow := false

valid_input if {
    input.schema_version == 1
    is_array(input.lines)
    count(input.lines) > 0
    every line in input.lines { valid_line(line) }
    is_array(input.python_issues)
    is_number(input.total_cents)
    is_number(input.food_cents)
    is_number(input.budget_cents)
    is_number(input.count)
    is_number(input.food_count)
    is_number(input.min_items)
    is_number(input.max_items)
    input.data_mode in {"strict", "simulation"}
    is_boolean(input.separate_budget)
    is_boolean(input.allergy_requested)
    is_string(input.catalog_revision)
    is_string(input.result_catalog_revision)
}

valid_line(line) if {
    is_number(line.quantity)
    is_number(line.unit_cents)
    is_number(line.reported_unit_cents)
    is_number(line.reported_subtotal_cents)
    line.unit_cents >= 0
    is_boolean(line.catalog_item)
    is_boolean(line.food)
    is_boolean(line.allergen_blocked)
    is_boolean(line.hard_excluded)
    is_boolean(line.only_allowed)
    is_boolean(line.evidence_confirmed)
}

deny contains "invalid_schema" if { not valid_input }
deny contains "python_validation_failed" if { count(input.python_issues) > 0 }
deny contains "catalog_changed" if { input.catalog_revision != input.result_catalog_revision }
deny contains "empty_food_set" if { input.food_count < 1 }
deny contains "too_few_items" if { input.count < input.min_items }
deny contains "too_many_items" if { input.count > input.max_items }
deny contains "invalid_budget" if { input.budget_cents <= 0 }
deny contains "invalid_budget" if { input.budget_cents > 10000000 }
deny contains "invalid_count_limits" if { input.min_items < 1 }
deny contains "invalid_count_limits" if { input.max_items > 60 }
deny contains "invalid_count_limits" if { input.min_items > input.max_items }
deny contains "over_budget" if { not input.separate_budget; input.total_cents > input.budget_cents }
deny contains "over_food_budget" if { input.separate_budget; input.food_cents > input.budget_cents }
deny contains "invalid_quantity" if { some line in input.lines; line.quantity < 1 }
deny contains "invalid_quantity" if { some line in input.lines; line.quantity != floor(line.quantity) }
deny contains "unknown_item" if { some line in input.lines; not line.catalog_item }
deny contains "too_many_repeats" if { some line in input.lines; line.food; line.quantity > 3 }
deny contains "allergen_conflict" if { some line in input.lines; line.allergen_blocked }
deny contains "hard_exclusion" if { some line in input.lines; line.hard_excluded }
deny contains "only_food_constraint" if { some line in input.lines; line.food; not line.only_allowed }
deny contains "unknown_allergen_evidence" if {
    input.data_mode == "strict"
    input.allergy_requested
    some line in input.lines
    not line.evidence_confirmed
}
deny contains "subtotal_mismatch" if {
    some line in input.lines
    line.reported_subtotal_cents != line.unit_cents * line.quantity
}
deny contains "unit_price_mismatch" if {
    some line in input.lines
    line.reported_unit_cents != line.unit_cents
}
deny contains "total_mismatch" if {
    input.total_cents != sum([value | line := input.lines[_]; value := line.unit_cents * line.quantity])
}
deny contains "food_total_mismatch" if {
    input.food_cents != sum([value | line := input.lines[_]; line.food; value := line.unit_cents * line.quantity])
}
deny contains "count_mismatch" if {
    input.count != sum([line.quantity | line := input.lines[_]])
}
allow if { valid_input; count(deny) == 0 }
decision := {"allow": allow, "deny_reasons": sort(deny), "policy_version": policy_version}
