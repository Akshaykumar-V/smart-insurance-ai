import type { PolicyList } from "./policies";
export const mockPolicies: PolicyList = { next_cursor: null, items: [
 { id: "demo-health-family", category: "health", policy_type: "family_floater", insurer: "Fictional Meadow Insurance", product_name: "Family Health Plus", sum_insured_paise: 100000000, start_date: "2026-01-01", end_date: "2026-12-31", analysis_status: "ready", needs_review: true },
 { id: "demo-health-individual", category: "health", policy_type: "individual", insurer: "Fictional Cedar Insurance", product_name: "Everyday Health", sum_insured_paise: null, start_date: null, end_date: null, analysis_status: "processing", needs_review: false },
 { id: "demo-vehicle", category: "vehicle", policy_type: "other", insurer: "Fictional Horizon Insurance", product_name: "Drive Secure", sum_insured_paise: 65000000, start_date: "2026-04-01", end_date: "2027-03-31", analysis_status: "unsupported", needs_review: false },
 { id: "demo-life", category: "life", policy_type: "individual", insurer: "Fictional Oak Life", product_name: "Tomorrow Term", sum_insured_paise: 1000000000, start_date: null, end_date: null, analysis_status: "unsupported", needs_review: false }
] };
