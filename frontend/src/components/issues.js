const LABELS = {
  low_confidence: 'Low confidence',
  utility_unknown: 'Utility unknown',
  multiple_meters: 'Several meters',
  estimated_read: 'Estimated read',
  model_notes: 'Model note',
  unit_missing: 'No unit',
  unit_not_allowed: 'Unit not allowed',
  unit_utility_mismatch: 'Unit/utility mismatch',
  period_missing: 'No billing period',
  period_order: 'Period end before start',
  period_too_long: 'Period too long',
  period_in_future: 'Period in future',
  quantity_missing: 'No quantity',
  quantity_not_positive: 'Quantity ≤ 0',
  meter_rollover: 'Meter rollover',
  meter_mismatch: 'Readings ≠ total',
  multiplier_not_printed: 'No multiplier',
  snippet_missing: 'No source snippet',
  snippet_page_invalid: 'Bad page reference',
  snippet_not_found: 'Snippet not on page',
  quantity_not_in_snippet: 'Quantity not in snippet',
  readings_not_on_page: 'Readings not on page',
  account_missing: 'No account number',
  account_unmapped: 'New account',
  account_other_facility: 'Account of other facility',
  overlapping_period: 'Overlaps another bill',
  outlier: 'Unusual consumption',
}

export function issueLabel(code) {
  return LABELS[code] || code
}
