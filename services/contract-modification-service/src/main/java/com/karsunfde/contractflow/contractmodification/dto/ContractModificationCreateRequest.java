package com.karsunfde.contractflow.contractmodification.dto;

import java.time.Instant;
import java.util.Map;

/**
 * Create-contractModification request DTO.
 *
 * ⚠ DELIBERATE — Item 9:
 *   No {@code @SafeHtml}, no {@code @NotBlank}, no length cap on
 *   {@code description}. The field accepts {@code <script>} tags verbatim.
 *   Cohort fixes in W4 Wed AI Security Engineering Day.
 *
 * ⚠ DELIBERATE — Item 10 reinforcement:
 *   {@code agencyId} is on the DTO but the controller doesn't cross-check it
 *   against the JWT's agency claim.
 *
 * Fields {@code sections}, {@code effectiveDate}, {@code popStart},
 * {@code popEnd} added to satisfy FAR Part 43 PATCH partial-update
 * contract (Codex Finding 5).
 */
public class ContractModificationCreateRequest {

    private String agencyId;
    private String title;
    private String description; // ⚠ raw HTML accepted (doubles as SF-30 change rationale)
    private String status;

    // --- SF-30 post-award modification fields (FAR Part 43) ---
    private String contractNumber;
    private String modificationNumber;
    private String modType;        // unilateral_change_order | unilateral_admin | bilateral_supplemental
    private String farAuthority;   // e.g. FAR 52.243-1
    private Double fundingDelta;   // net obligation change, USD
    private boolean contractorConsentRequired;

    // --- Partial-update fields (Codex Finding 5 — PATCH support) ---
    /** Free-form sub-sections keyed by name (mirrors ContractModification.sections). */
    private Map<String, String> sections;
    /** Issue date (unilateral) or mutually agreed effective date (bilateral). */
    private Instant effectiveDate;
    /** Revised period-of-performance start. */
    private Instant popStart;
    /** Revised period-of-performance end. */
    private Instant popEnd;

    // --- Execute/publish fields (Codex Finding 2 — bilateral consent) ---
    /**
     * Set to true when contractor consent has been recorded in the modification
     * package. Required for bilateral (contractorConsentRequired) mods before
     * executeModification/publish may proceed (FAR 43.103(a)(2)).
     */
    private boolean consentRecorded;
    /** SHA-256 of the signed modification package; persisted on the audit record. */
    private String packageHash;

    public ContractModificationCreateRequest() {}

    public String getAgencyId() { return agencyId; }
    public void setAgencyId(String agencyId) { this.agencyId = agencyId; }
    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }
    public String getDescription() { return description; }
    public void setDescription(String description) { this.description = description; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }

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
    public boolean isContractorConsentRequired() { return contractorConsentRequired; }
    public void setContractorConsentRequired(boolean contractorConsentRequired) { this.contractorConsentRequired = contractorConsentRequired; }

    public Map<String, String> getSections() { return sections; }
    public void setSections(Map<String, String> sections) { this.sections = sections; }
    public Instant getEffectiveDate() { return effectiveDate; }
    public void setEffectiveDate(Instant effectiveDate) { this.effectiveDate = effectiveDate; }
    public Instant getPopStart() { return popStart; }
    public void setPopStart(Instant popStart) { this.popStart = popStart; }
    public Instant getPopEnd() { return popEnd; }
    public void setPopEnd(Instant popEnd) { this.popEnd = popEnd; }

    public boolean isConsentRecorded() { return consentRecorded; }
    public void setConsentRecorded(boolean consentRecorded) { this.consentRecorded = consentRecorded; }
    public String getPackageHash() { return packageHash; }
    public void setPackageHash(String packageHash) { this.packageHash = packageHash; }
}
