package com.karsunfde.contractflow.invoicereview.model;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.mapping.Document;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * InvoiceReview record — post-award invoice / payment review (FAR Part 32,
 * anchor: WAWF). Replaces the pre-award source-selection panel.
 *
 * Domain: a vendor submits a payment request (invoice) against an awarded
 * contract's CLINs. The COR matches it to the receiving report, runs the
 * proper-invoice checklist (FAR 32.905 required elements), and either
 * certifies it for payment or returns it as improper (FAR 32.905(b) — must
 * return within 7 days). Prompt-Payment due date = receipt + 30 days
 * (5 CFR 1315). Cost-type invoices may carry DCAA audit flags.
 *
 * Payment status: received → proper → certified → paid
 *                          ↘ improper_returned
 *
 * ⚠ Item 3 — fetching the contract/CLIN snapshot for review is the canonical
 * reproducer for the no-circuit-breaker debt (review → contract-modification-service
 * hot loop). The legacy panel-state fields below (state/panelMembers/factorIds/
 * ssddDocId) are retained so the W3 cohort can repurpose the source-selection
 * surface; they are not part of the FAR 32 payment spine.
 */
@Document(collection = "invoiceReviews")
public class InvoiceReview {

    @Id
    private String id;

    private String contractModificationId;
    private String agencyId;
    private String state;

    // --- FAR 32 invoice / payment fields ---
    /** Awarded contract this invoice bills against, e.g. GS-35F-0001V. */
    private String contractNumber;
    /** Contractor-assigned invoice number. */
    private String invoiceNumber;
    /** Invoice date submitted by the contractor. */
    private Instant invoiceDate;
    /** WAWF receiving-report reference matched against the invoice. */
    private String receivingReportRef;
    /** Total invoiced amount across all CLIN line items (USD). */
    private Double invoiceAmount;
    /**
     * FAR 32.905 proper-invoice checklist results keyed by required element
     * (contractorName, invoiceDate, contractNumber, description, quantities,
     * unitPrices, shippingTerms, payeeAddress) → present/absent.
     */
    private Map<String, Boolean> properInvoiceChecks = new HashMap<>();
    /** received | proper | improper_returned | certified | paid */
    private String paymentStatus;
    /** Prompt-Payment due date = invoice receipt + 30 days (5 CFR 1315). */
    private Instant promptPayDueDate;
    /** If returned improper, the reason (FAR 32.905(b)); return within 7 days. */
    private String returnReason;
    /** DCAA cost-type audit flags (e.g. unallowable cost FAR 31.205, defective pricing). */
    private List<String> dcaaFlags = new ArrayList<>();

    // --- Legacy source-selection panel fields (retained for W3 repurpose) ---
    private List<String> panelMembers = new ArrayList<>();
    private List<String> factorIds = new ArrayList<>();
    private Instant createdAt;
    private Instant consensusAt;
    private String ssddDocId;

    public InvoiceReview() {}

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getContractModificationId() { return contractModificationId; }
    public void setContractModificationId(String contractModificationId) { this.contractModificationId = contractModificationId; }
    public String getAgencyId() { return agencyId; }
    public void setAgencyId(String agencyId) { this.agencyId = agencyId; }
    public String getState() { return state; }
    public void setState(String state) { this.state = state; }

    public String getContractNumber() { return contractNumber; }
    public void setContractNumber(String contractNumber) { this.contractNumber = contractNumber; }
    public String getInvoiceNumber() { return invoiceNumber; }
    public void setInvoiceNumber(String invoiceNumber) { this.invoiceNumber = invoiceNumber; }
    public Instant getInvoiceDate() { return invoiceDate; }
    public void setInvoiceDate(Instant invoiceDate) { this.invoiceDate = invoiceDate; }
    public String getReceivingReportRef() { return receivingReportRef; }
    public void setReceivingReportRef(String receivingReportRef) { this.receivingReportRef = receivingReportRef; }
    public Double getInvoiceAmount() { return invoiceAmount; }
    public void setInvoiceAmount(Double invoiceAmount) { this.invoiceAmount = invoiceAmount; }
    public Map<String, Boolean> getProperInvoiceChecks() { return properInvoiceChecks; }
    public void setProperInvoiceChecks(Map<String, Boolean> properInvoiceChecks) { this.properInvoiceChecks = properInvoiceChecks; }
    public String getPaymentStatus() { return paymentStatus; }
    public void setPaymentStatus(String paymentStatus) { this.paymentStatus = paymentStatus; }
    public Instant getPromptPayDueDate() { return promptPayDueDate; }
    public void setPromptPayDueDate(Instant promptPayDueDate) { this.promptPayDueDate = promptPayDueDate; }
    public String getReturnReason() { return returnReason; }
    public void setReturnReason(String returnReason) { this.returnReason = returnReason; }
    public List<String> getDcaaFlags() { return dcaaFlags; }
    public void setDcaaFlags(List<String> dcaaFlags) { this.dcaaFlags = dcaaFlags; }

    public List<String> getPanelMembers() { return panelMembers; }
    public void setPanelMembers(List<String> panelMembers) { this.panelMembers = panelMembers; }
    public List<String> getFactorIds() { return factorIds; }
    public void setFactorIds(List<String> factorIds) { this.factorIds = factorIds; }
    public Instant getCreatedAt() { return createdAt; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }
    public Instant getConsensusAt() { return consensusAt; }
    public void setConsensusAt(Instant consensusAt) { this.consensusAt = consensusAt; }
    public String getSsddDocId() { return ssddDocId; }
    public void setSsddDocId(String ssddDocId) { this.ssddDocId = ssddDocId; }
}
