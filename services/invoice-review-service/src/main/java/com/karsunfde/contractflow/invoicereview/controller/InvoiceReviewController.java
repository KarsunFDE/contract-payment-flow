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
 *   duplicate invoiceReviews.
 */
@RestController
@RequestMapping("/api/invoice-reviews")
public class InvoiceReviewController {

    private final ContractModificationClient contractModificationClient;
    private final InvoiceReviewService svc;

    @Autowired
    public InvoiceReviewController(ContractModificationClient contractModificationClient, InvoiceReviewService svc) {
        this.contractModificationClient = contractModificationClient;
        this.svc = svc;
    }

    /** Fetch the contractModification snapshot the invoiceReview panel is reviewing. */
    @GetMapping("/{invoiceReviewId}/contractModification/{contractModificationId}")
    public ResponseEntity<Map<String, Object>> getContractModificationForInvoiceReview(
            @PathVariable String invoiceReviewId,
            @PathVariable String contractModificationId) {
        // ⚠ Item 3 — no circuit breaker on this hop.
        Map<String, Object> sol = contractModificationClient.getContractModification(contractModificationId);
        return ResponseEntity.ok(sol);
    }

    /** Create a new invoiceReview panel. ⚠ Item 3 — no idempotency key. */
    @PostMapping
    public ResponseEntity<InvoiceReview> create(@RequestBody Map<String, Object> req,
                                              @RequestHeader(value = "X-User", defaultValue = "anonymous") String actor) {
        String contractModificationId = String.valueOf(req.get("contractModificationId"));
        String agencyId = (String) req.getOrDefault("agencyId", "GSA-FAS");
        return ResponseEntity.ok(svc.create(contractModificationId, agencyId, actor));
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
