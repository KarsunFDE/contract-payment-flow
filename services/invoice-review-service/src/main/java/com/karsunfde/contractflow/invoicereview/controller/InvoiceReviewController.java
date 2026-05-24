package com.karsunfde.contractflow.invoicereview.controller;

import com.karsunfde.contractflow.invoicereview.client.ContractModificationClient;
import com.karsunfde.contractflow.invoicereview.model.InvoiceReview;
import com.karsunfde.contractflow.invoicereview.model.InvoiceReviewScore;
import com.karsunfde.contractflow.invoicereview.service.InvoiceReviewService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * InvoiceReview panel REST surface — Workflow 4 (eval → consensus → SSDD).
 *
 * Endpoints (feature-inventory-target.md, invoice-review-service rows):
 *   POST   /api/invoice-reviews
 *   GET    /api/invoice-reviews/{id}
 *   POST   /api/invoice-reviews/{id}/panel
 *   POST   /api/invoice-reviews/{id}/scores
 *   GET    /api/invoice-reviews/{id}/consensus
 *   POST   /api/invoice-reviews/{id}/ssdd
 *
 * ⚠ DELIBERATE — Item 3 reinforcement:
 *   POST /api/invoice-reviews is a state-mutating endpoint that does NOT accept
 *   or honour an Idempotency-Key header. A retry from the client creates
 *   duplicate invoice_reviews.
 */
@RestController
@RequestMapping("/api/invoice-reviews")
public class InvoiceReviewController {

    private final ContractModificationClient contract_modificationClient;
    private final InvoiceReviewService svc;

    @Autowired
    public InvoiceReviewController(ContractModificationClient contract_modificationClient, InvoiceReviewService svc) {
        this.contractmodificationClient = contract_modificationClient;
        this.svc = svc;
    }

    /** Fetch the contract_modification snapshot the invoice_review panel is reviewing. */
    @GetMapping("/{invoice_reviewId}/contract_modification/{contract_modificationId}")
    public ResponseEntity<Map<String, Object>> getContractModificationForInvoiceReview(
            @PathVariable String invoice_reviewId,
            @PathVariable String contract_modificationId) {
        // ⚠ Item 3 — no circuit breaker on this hop.
        Map<String, Object> sol = contract_modificationClient.getContractModification(contract_modificationId);
        return ResponseEntity.ok(sol);
    }

    /** Create a new invoice_review panel. ⚠ Item 3 — no idempotency key. */
    @PostMapping
    public ResponseEntity<InvoiceReview> create(@RequestBody Map<String, Object> req,
                                              @RequestHeader(value = "X-User", defaultValue = "anonymous") String actor) {
        String contract_modificationId = String.valueOf(req.get("contract_modificationId"));
        String agencyId = (String) req.getOrDefault("agencyId", "GSA-FAS");
        return ResponseEntity.ok(svc.create(contract_modificationId, agencyId, actor));
    }

    @GetMapping("/{id}")
    public ResponseEntity<InvoiceReview> get(@PathVariable String id) {
        return svc.findById(id)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }

    @PostMapping("/{id}/panel")
    public ResponseEntity<InvoiceReview> assignPanel(
            @PathVariable String id,
            @RequestBody Map<String, List<String>> body,
            @RequestHeader(value = "X-User", defaultValue = "anonymous") String actor) {
        return svc.assignPanel(id, body.getOrDefault("panelMembers", List.of()), actor)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }

    @PostMapping("/{id}/scores")
    public ResponseEntity<InvoiceReviewScore> submitScore(
            @PathVariable String id,
            @RequestBody InvoiceReviewScore score,
            @RequestHeader(value = "X-User", defaultValue = "anonymous") String actor) {
        return svc.submitScore(id, score, actor)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }

    @GetMapping("/{id}/consensus")
    public Map<String, Map<String, Double>> consensus(@PathVariable String id) {
        return svc.consensus(id);
    }

    @PostMapping("/{id}/ssdd")
    public ResponseEntity<Map<String, Object>> ssdd(
            @PathVariable String id,
            @RequestHeader(value = "X-User", defaultValue = "anonymous") String actor) {
        return svc.draftSsdd(id, actor)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }
}
