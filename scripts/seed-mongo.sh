#!/usr/bin/env bash
# Seed the local MongoDB with a few demo post-award records:
# awarded contracts, SF-30 contract modifications, and invoices/payment status.
# Usage:  ./scripts/seed-mongo.sh   (run after `docker-compose up`)
#
# NOTE (reshape 2026-05-28): previously seeded db.solicitations (pre-award,
# wrong collection + wrong domain). Now seeds the renamed entity collections
# that match the Spring @Document mappings:
#   - contractModifications  (ContractModification.java — SF-30 mods)
#   - invoiceReviews         (InvoiceReview.java — FAR 32 invoice/payment)
#   - contracts              (awarded-contract anchors)
# DB name contract_payment_flow matches domain-mapping.md (was acquire_gov).

set -euo pipefail

MONGO_URL="${MONGO_URL:-mongodb://app:app_dev_password@localhost:27017}"

cat <<'EOF' | docker run --rm -i --network host mongo:7 mongosh "$MONGO_URL/contract_payment_flow?authSource=admin"
// --- Awarded contracts (post-award anchors) ---
db.contracts.insertMany([
  {
    agencyId: "GSA-FAS",
    contractNumber: "GS-35F-0001V",
    title: "Cloud Managed Services BPA — Civilian Agencies",
    contractor: "Acme Federal LLC",
    awardedAt: new Date("2025-08-01"),
    ceilingValue: 110000000,
    status: "ACTIVE",
    createdAt: new Date(),
    updatedAt: new Date()
  },
  {
    agencyId: "DLA",
    contractNumber: "SPE7M5-24-D-0042",
    title: "Depot Spares — IDIQ",
    contractor: "Globex Federal Systems",
    awardedAt: new Date("2024-11-15"),
    ceilingValue: 25000000,
    status: "ACTIVE",
    createdAt: new Date(),
    updatedAt: new Date()
  }
]);
print("Seeded " + db.contracts.countDocuments() + " contracts.");

// --- SF-30 contract modifications (FAR Part 43) ---
db.contractModifications.insertMany([
  {
    agencyId: "GSA-FAS",
    contractNumber: "GS-35F-0001V",
    modificationNumber: "P00003",
    modType: "bilateral_supplemental",
    farAuthority: "FAR 43.103 / FAR 52.243-1",
    title: "Exercise Option Year 2 + add funds",
    description: "<p>Exercise OY2 and add incremental funding; PoP extended 12 months.</p>",
    fundingDelta: 18000000,
    contractorConsentRequired: true,
    status: "MODIFICATION_REQUEST",
    effectiveDate: new Date(),
    createdAt: new Date(),
    updatedAt: new Date()
  },
  {
    agencyId: "GSA-FAS",
    contractNumber: "GS-35F-0001V",
    modificationNumber: "A00002",
    modType: "unilateral_admin",
    farAuthority: "FAR 43.101 (administrative change)",
    title: "Administrative — update CO POC after transition",
    description: "Administrative change: revise Block 7 CO point-of-contact email.",
    fundingDelta: 0,
    contractorConsentRequired: false,
    status: "PERFORMANCE_MONITORING",
    effectiveDate: new Date(),
    createdAt: new Date(),
    updatedAt: new Date()
  }
]);
print("Seeded " + db.contractModifications.countDocuments() + " contract modifications.");

// --- Invoices / payment review (FAR Part 32) ---
db.invoiceReviews.insertMany([
  {
    agencyId: "GSA-FAS",
    contractNumber: "GS-35F-0001V",
    invoiceNumber: "INV-2026-0412",
    invoiceDate: new Date(),
    receivingReportRef: "WAWF-RR-88213",
    invoiceAmount: 482350.00,
    properInvoiceChecks: {
      contractor_name_address: true, invoice_date: true, contract_number: true,
      description_of_supplies_services: true, quantities_unit_prices: true,
      shipping_payment_terms: true, payee_name_address: true
    },
    paymentStatus: "certified",
    promptPayDueDate: new Date(Date.now() + 1000 * 60 * 60 * 24 * 30),
    dcaaFlags: [],
    state: "INVOICE_PROCESSING",
    createdAt: new Date()
  },
  {
    agencyId: "GSA-FAS",
    contractNumber: "GS-35F-0001V",
    invoiceNumber: "INV-2026-0415",
    invoiceDate: new Date(),
    receivingReportRef: null,
    invoiceAmount: 91200.00,
    properInvoiceChecks: {
      contractor_name_address: true, invoice_date: true, contract_number: true,
      description_of_supplies_services: true, quantities_unit_prices: false,
      shipping_payment_terms: true, payee_name_address: true
    },
    paymentStatus: "improper_returned",
    returnReason: "Missing unit prices for CLIN 0002 (FAR 32.905(b)); RR unmatched.",
    promptPayDueDate: null,
    dcaaFlags: ["unit_price_variance"],
    state: "INVOICE_PROCESSING",
    createdAt: new Date()
  }
]);
print("Seeded " + db.invoiceReviews.countDocuments() + " invoice reviews.");
EOF
