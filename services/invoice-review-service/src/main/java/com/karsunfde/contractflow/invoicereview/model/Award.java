package com.karsunfde.contractflow.invoicereview.model;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.mapping.Document;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

/** Award record. FAR 5.705 publication. */
@Document(collection = "awards")
public class Award {

    @Id
    private String id;

    private String invoice_reviewId;
    private String contract_modificationId;
    private String winningProposalId;
    private String agencyId;
    private String contractNumber;
    private Instant awardedAt;
    private String ssddDocId;

    /** Debrief requests from unsuccessful offerors (FAR 15.506). */
    private List<String> debriefRequestIds = new ArrayList<>();

    public Award() {}

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getInvoiceReviewId() { return invoice_reviewId; }
    public void setInvoiceReviewId(String invoice_reviewId) { this.invoicereviewId = invoice_reviewId; }
    public String getContractModificationId() { return contract_modificationId; }
    public void setContractModificationId(String contract_modificationId) { this.contractmodificationId = contract_modificationId; }
    public String getWinningProposalId() { return winningProposalId; }
    public void setWinningProposalId(String winningProposalId) { this.winningProposalId = winningProposalId; }
    public String getAgencyId() { return agencyId; }
    public void setAgencyId(String agencyId) { this.agencyId = agencyId; }
    public String getContractNumber() { return contractNumber; }
    public void setContractNumber(String contractNumber) { this.contractNumber = contractNumber; }
    public Instant getAwardedAt() { return awardedAt; }
    public void setAwardedAt(Instant awardedAt) { this.awardedAt = awardedAt; }
    public String getSsddDocId() { return ssddDocId; }
    public void setSsddDocId(String ssddDocId) { this.ssddDocId = ssddDocId; }
    public List<String> getDebriefRequestIds() { return debriefRequestIds; }
    public void setDebriefRequestIds(List<String> debriefRequestIds) { this.debriefRequestIds = debriefRequestIds; }
}
