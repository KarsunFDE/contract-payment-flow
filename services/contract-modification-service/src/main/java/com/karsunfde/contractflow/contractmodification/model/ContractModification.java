package com.karsunfde.contractflow.contractmodification.model;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.mapping.Document;

import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

/**
 * ContractModification document — a post-award SF-30 (Standard Form 30,
 * "Amendment of Solicitation / Modification of Contract"). Drives the
 * cohort's W1 Tue inventory walkthrough.
 *
 * Domain (post-award contract administration, anchor: WAWF):
 *   A modification changes an awarded contract — adds/removes funds, shifts
 *   the period of performance, or revises scope under a FAR Part 43 Changes
 *   authority. Unilateral mods (change order / administrative) are signed by
 *   the CO alone; bilateral supplemental agreements require contractor
 *   consent. See FAR 43.103 (definitions) and FAR 43.301 (use of SF-30).
 *
 * ⚠ DELIBERATE — Item 10:
 *   {@code agencyId} is in the schema (so the data is multi-tenant-shaped)
 *   but the repository does not filter on it. Cohort fixes in W2 Wed
 *   multi-tenant retrieval-boundary work.
 *
 * ⚠ DELIBERATE — Item 9:
 *   {@code description} is not sanitized; arbitrary HTML accepted on write
 *   and returned verbatim on read. Cohort fixes in W4 Wed AI Security
 *   Engineering Day (prompt-injection-via-stored-content — description /
 *   changeRationale feed the ai-orchestrator prompt). The {@code sections}
 *   map carries the same un-sanitized-text debt.
 *
 * State machine (post-award modification lifecycle):
 *   MODIFICATION_REQUEST -> PERFORMANCE_MONITORING -> INVOICE_PROCESSING -> CLOSEOUT
 *   CANCELLED is reachable from any pre-CLOSEOUT state.
 *   (Legacy DRAFT/INTERNAL_REVIEW/PUBLISHED values still flow through as raw
 *    strings — {@code status} is untyped — so existing fixtures keep loading.)
 */
@Document(collection = "contractModifications")
public class ContractModification {

    @Id
    private String id;

    /** ⚠ Item 10 — present but un-enforced. */
    private String agencyId;

    private String title;

    /** ⚠ Item 9 — accepts arbitrary HTML. Doubles as the SF-30 change rationale. */
    private String description;

    private String status;

    // --- SF-30 post-award modification fields (FAR Part 43) ---

    /** Base contract being modified, e.g. GS-35F-0001V. */
    private String contractNumber;
    /** SF-30 modification number, e.g. P00001 (supplemental) / A00001 (admin). */
    private String modificationNumber;
    /**
     * Modification type per FAR 43:
     *   unilateral_change_order | unilateral_admin | bilateral_supplemental
     */
    private String modType;
    /** FAR authority cite for the change, e.g. FAR 52.243-1 (Changes — FFP). */
    private String farAuthority;
    /** Net funding change (USD); positive = add funds, negative = deobligate. */
    private Double fundingDelta;
    /** Revised period-of-performance start (if PoP changes). */
    private Instant popStart;
    /** Revised period-of-performance end (if PoP changes). */
    private Instant popEnd;
    /** Issue date (unilateral) / mutually agreed effective date (bilateral). */
    private Instant effectiveDate;
    /** True for bilateral supplemental agreements (contractor signature required). */
    private boolean contractorConsentRequired;

    /** NAICS code (legacy pre-award field — retained for inherited fixtures). */
    private String naics;
    /** Set-aside category (legacy pre-award field — retained for inherited fixtures). */
    private String setAside;

    /**
     * Free-form sub-sections keyed by name (e.g. changeNarrative,
     * priceCostImpact, fundingCitation). Stored as a map so the cohort can
     * extend without schema changes. ⚠ Item 9 — values unsanitized; feed the
     * /draft-contract-modification prompt.
     */
    private Map<String, String> sections = new HashMap<>();

    private Instant postedAt;
    private Instant closingAt;
    private Instant createdAt;
    private Instant updatedAt;

    public ContractModification() {}

    // --- getters / setters ---

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getAgencyId() { return agencyId; }
    public void setAgencyId(String agencyId) { this.agencyId = agencyId; }

    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }

    public String getDescription() { return description; }
    public void setDescription(String description) { this.description = description; }

    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }

    public String getNaics() { return naics; }
    public void setNaics(String naics) { this.naics = naics; }

    public String getSetAside() { return setAside; }
    public void setSetAside(String setAside) { this.setAside = setAside; }

    public String getContractNumber() { return contractNumber; }
    public void setContractNumber(String contractNumber) { this.contractNumber = contractNumber; }

    public String getModificationNumber() { return modificationNumber; }
    public void setModificationNumber(String modificationNumber) { this.modificationNumber = modificationNumber; }

    public String getModType() { return modType; }
    public void setModType(String modType) { this.modType = modType; }

    public String getFarAuthority() { return farAuthority; }
    public void setFarAuthority(String farAuthority) { this.farAuthority = farAuthority; }

    public Double getFundingDelta() { return fundingDelta; }
    public void setFundingDelta(Double fundingDelta) { this.fundingDelta = fundingDelta; }

    public Instant getPopStart() { return popStart; }
    public void setPopStart(Instant popStart) { this.popStart = popStart; }

    public Instant getPopEnd() { return popEnd; }
    public void setPopEnd(Instant popEnd) { this.popEnd = popEnd; }

    public Instant getEffectiveDate() { return effectiveDate; }
    public void setEffectiveDate(Instant effectiveDate) { this.effectiveDate = effectiveDate; }

    public boolean isContractorConsentRequired() { return contractorConsentRequired; }
    public void setContractorConsentRequired(boolean contractorConsentRequired) { this.contractorConsentRequired = contractorConsentRequired; }

    public Map<String, String> getSections() { return sections; }
    public void setSections(Map<String, String> sections) { this.sections = sections; }

    public Instant getPostedAt() { return postedAt; }
    public void setPostedAt(Instant postedAt) { this.postedAt = postedAt; }

    public Instant getClosingAt() { return closingAt; }
    public void setClosingAt(Instant closingAt) { this.closingAt = closingAt; }

    public Instant getCreatedAt() { return createdAt; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }

    public Instant getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(Instant updatedAt) { this.updatedAt = updatedAt; }
}
