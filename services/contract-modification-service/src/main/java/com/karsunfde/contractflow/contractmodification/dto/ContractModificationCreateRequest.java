package com.karsunfde.contractflow.contractmodification.dto;

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
}
