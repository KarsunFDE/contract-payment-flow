package com.karsunfde.contractflow.contractmodification.controller;

import com.karsunfde.contractflow.contractmodification.dto.AmendmentRequest;
import com.karsunfde.contractflow.contractmodification.dto.ProposalSubmitRequest;
import com.karsunfde.contractflow.contractmodification.dto.QnaAnswerRequest;
import com.karsunfde.contractflow.contractmodification.dto.QnaRequest;
import com.karsunfde.contractflow.contractmodification.dto.ContractModificationCreateRequest;
import com.karsunfde.contractflow.contractmodification.model.Amendment;
import com.karsunfde.contractflow.contractmodification.model.Proposal;
import com.karsunfde.contractflow.contractmodification.model.Qna;
import com.karsunfde.contractflow.contractmodification.model.ContractModification;
import com.karsunfde.contractflow.contractmodification.service.AmendmentService;
import com.karsunfde.contractflow.contractmodification.service.ProposalService;
import com.karsunfde.contractflow.contractmodification.service.QnaService;
import com.karsunfde.contractflow.contractmodification.service.ContractModificationService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * ContractModification REST surface — covers Workflow 1 (drafting → execution),
 * Workflow 2 (Q&A + amendments), Workflow 3 (proposal intake).
 *
 * Endpoints (feature-inventory-target.md, contract-modification-service rows):
 *   POST    /api/contract-modifications
 *   GET     /api/contract-modifications
 *   GET     /api/contract-modifications/{id}
 *   PUT     /api/contract-modifications/{id}
 *   PATCH   /api/contract-modifications/{id}         (Codex Finding 5)
 *   DELETE  /api/contract-modifications/{id}
 *   POST    /api/contract-modifications/{id}/publish  (delegates to executeModification)
 *   POST    /api/contract-modifications/{id}/execute  (Codex Finding 3 — DRAFT→MODIFICATION_REQUEST)
 *   POST    /api/contract-modifications/{id}/cancel
 *   POST    /api/contract-modifications/{id}/amendments
 *   GET     /api/contract-modifications/{id}/amendments
 *   POST    /api/contract-modifications/{id}/qa
 *   PUT     /api/contract-modifications/{id}/qa/{qnaId}/answer
 *   GET     /api/contract-modifications/{id}/qa
 *   POST    /api/contract-modifications/{id}/proposals
 *   GET     /api/contract-modifications/{id}/proposals
 *   POST    /api/contract-modifications/{id}/proposals/{pid}/acknowledge-amendment
 *
 * All state-mutating routes require headers:
 *   X-User-Id    — authenticated user identifier (no defaultValue — Codex Finding 1)
 *   X-User-Role  — caller's role; execute/cancel additionally require CONTRACTING_OFFICER
 *   X-Tenant-Id  — caller's agency; execute/cancel enforce agency == modification.agencyId
 *   X-Correlation-Id — optional, propagated for log tracing
 */
@RestController
@RequestMapping("/api/contract-modifications")
public class ContractModificationController {

    private final ContractModificationService svc;
    private final AmendmentService amendmentSvc;
    private final QnaService qnaSvc;
    private final ProposalService proposalSvc;

    @Autowired
    public ContractModificationController(ContractModificationService svc,
                                  AmendmentService amendmentSvc,
                                  QnaService qnaSvc,
                                  ProposalService proposalSvc) {
        this.svc = svc;
        this.amendmentSvc = amendmentSvc;
        this.qnaSvc = qnaSvc;
        this.proposalSvc = proposalSvc;
    }

    @GetMapping
    public List<ContractModification> list(
            @RequestHeader(value = "X-User-Id") String userId,
            @RequestHeader(value = "X-User-Role") String role,
            @RequestHeader(value = "X-Tenant-Id") String tenantId) {
        // Item 10 (no-multi-tenant-boundary) — FIXED week 4 (was scheduled W2-Wed).
        //   WAS: this private listing called svc.listAll() -> repo.findAll(),
        //        leaking contractModifications across ALL agencies (cross-tenant leak).
        //   NOW: scoped to the caller's agency from X-Tenant-Id via
        //        svc.listAll(tenantId) -> repo.findByAgencyId(...). The cross-tenant
        //        no-arg svc.listAll() survives ONLY for the public opportunities surface.
        return svc.listAll(tenantId);
    }

    @GetMapping("/{id}")
    public ResponseEntity<ContractModification> get(@PathVariable String id) {
        return svc.findById(id)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }

    @PostMapping
    public ResponseEntity<ContractModification> create(
            @RequestBody ContractModificationCreateRequest req,
            @RequestHeader(value = "X-User-Id") String userId,
            @RequestHeader(value = "X-User-Role") String role,
            @RequestHeader(value = "X-Tenant-Id") String tenantId) {
        // ⚠ Item 9 — no validation on req.description. Fix is W4-Wed fair game
        //   but requires the org.jsoup:jsoup dependency in pom.xml before
        //   Jsoup.clean() can be called here. Unblocked; pending dep addition.
        ContractModification created = svc.create(req, userId, role, tenantId);
        return ResponseEntity.ok(created);
    }

    @PutMapping("/{id}")
    public ResponseEntity<ContractModification> update(
            @PathVariable String id,
            @RequestBody ContractModificationCreateRequest req,
            @RequestHeader(value = "X-User-Id") String userId,
            @RequestHeader(value = "X-User-Role") String role,
            @RequestHeader(value = "X-Tenant-Id") String tenantId) {
        return svc.update(id, req, userId, role, tenantId)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }

    /**
     * Partial update — only supplied fields are applied.
     * Codex Finding 5: accepts sections, effectiveDate, popStart, popEnd.
     */
    @PatchMapping("/{id}")
    public ResponseEntity<ContractModification> patch(
            @PathVariable String id,
            @RequestBody ContractModificationCreateRequest req,
            @RequestHeader(value = "X-User-Id") String userId,
            @RequestHeader(value = "X-User-Role") String role,
            @RequestHeader(value = "X-Tenant-Id") String tenantId) {
        return svc.patch(id, req, userId, role, tenantId)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(
            @PathVariable String id,
            @RequestHeader(value = "X-User-Id") String userId,
            @RequestHeader(value = "X-User-Role") String role,
            @RequestHeader(value = "X-Tenant-Id") String tenantId) {
        boolean ok = svc.delete(id, userId, role, tenantId);
        return ok ? ResponseEntity.noContent().build() : ResponseEntity.notFound().build();
    }

    // -------- State machine transitions (Workflow 1) --------

    /**
     * Execute a post-award modification: DRAFT → MODIFICATION_REQUEST.
     * Requires CONTRACTING_OFFICER role and matching agency (Codex Findings 1–4).
     * Body: { "consentRecorded": bool, "packageHash": "..." } (Codex Finding 2).
     * Other body fields are ignored on this route.
     */
    @PostMapping("/{id}/execute")
    public ResponseEntity<ContractModification> executeModification(
            @PathVariable String id,
            @RequestBody ContractModificationCreateRequest req,
            @RequestHeader(value = "X-User-Id") String userId,
            @RequestHeader(value = "X-User-Role") String role,
            @RequestHeader(value = "X-Tenant-Id") String tenantId,
            @RequestHeader(value = "X-Correlation-Id", required = false) String correlationId) {
        return svc.executeModification(id, req.isConsentRecorded(), req.getPackageHash(),
                userId, role, tenantId, correlationId)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }

    /**
     * Legacy publish route — delegates to executeModification so all guards apply.
     * Retained for backward compatibility with callers not yet migrated to /execute.
     * Body: { "consentRecorded": bool, "packageHash": "..." } (Codex Finding 2).
     * Other body fields are ignored on this route.
     */
    @PostMapping("/{id}/publish")
    public ResponseEntity<ContractModification> publish(
            @PathVariable String id,
            @RequestBody ContractModificationCreateRequest req,
            @RequestHeader(value = "X-User-Id") String userId,
            @RequestHeader(value = "X-User-Role") String role,
            @RequestHeader(value = "X-Tenant-Id") String tenantId,
            @RequestHeader(value = "X-Correlation-Id", required = false) String correlationId) {
        return svc.publish(id, req.isConsentRecorded(), req.getPackageHash(),
                userId, role, tenantId, correlationId)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }

    @PostMapping("/{id}/cancel")
    public ResponseEntity<ContractModification> cancel(
            @PathVariable String id,
            @RequestHeader(value = "X-User-Id") String userId,
            @RequestHeader(value = "X-User-Role") String role,
            @RequestHeader(value = "X-Tenant-Id") String tenantId,
            @RequestHeader(value = "X-Correlation-Id", required = false) String correlationId) {
        return svc.cancel(id, userId, role, tenantId, correlationId)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }

    // -------- Amendments (Workflow 2 — FAR 15.206) --------

    @PostMapping("/{id}/amendments")
    public ResponseEntity<Amendment> issueAmendment(
            @PathVariable String id,
            @RequestBody AmendmentRequest req,
            @RequestHeader(value = "X-User-Id") String userId,
            @RequestHeader(value = "X-User-Role") String role,
            @RequestHeader(value = "X-Tenant-Id") String tenantId) {
        return amendmentSvc.issue(id, req, userId)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }

    @GetMapping("/{id}/amendments")
    public List<Amendment> listAmendments(@PathVariable String id) {
        // ⚠ Item 10 — does not re-check caller agency. Full fix requires
        //   AmendmentService.listForContractModification to accept agencyId;
        //   that service is outside the allowed edit scope for this PR.
        return amendmentSvc.listForContractModification(id);
    }

    // -------- Q&A (Workflow 2) --------

    @PostMapping("/{id}/qa")
    public ResponseEntity<Qna> submitQuestion(
            @PathVariable String id,
            @RequestBody QnaRequest req,
            @RequestHeader(value = "X-User-Id") String userId,
            @RequestHeader(value = "X-User-Role") String role,
            @RequestHeader(value = "X-Tenant-Id") String tenantId) {
        return qnaSvc.submit(id, req, userId)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }

    @PutMapping("/{id}/qa/{qnaId}/answer")
    public ResponseEntity<Qna> answer(
            @PathVariable String id,
            @PathVariable String qnaId,
            @RequestBody QnaAnswerRequest req,
            @RequestHeader(value = "X-User-Id") String userId,
            @RequestHeader(value = "X-User-Role") String role,
            @RequestHeader(value = "X-Tenant-Id") String tenantId) {
        return qnaSvc.answer(qnaId, req, userId)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }

    @GetMapping("/{id}/qa")
    public List<Qna> listQna(@PathVariable String id) {
        // ⚠ Item 10 — vendor should only see their own pre-publish entries.
        return qnaSvc.listForContractModification(id);
    }

    // -------- Proposal intake (Workflow 3) --------

    @PostMapping("/{id}/proposals")
    public ResponseEntity<Proposal> submitProposal(
            @PathVariable String id,
            @RequestBody ProposalSubmitRequest req,
            @RequestHeader(value = "X-User-Id") String userId,
            @RequestHeader(value = "X-User-Role") String role,
            @RequestHeader(value = "X-Tenant-Id") String tenantId) {
        return proposalSvc.submit(id, req, userId)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }

    @GetMapping("/{id}/proposals")
    public List<Proposal> listProposals(@PathVariable String id) {
        // ⚠ Item 2 — must be gated on post-deadline + audit-logged on view.
        // ⚠ Item 10 — does not re-check caller agency.
        return proposalSvc.listForContractModification(id);
    }

    @PostMapping("/{id}/proposals/{pid}/acknowledge-amendment")
    public ResponseEntity<Proposal> acknowledgeAmendment(
            @PathVariable String id,
            @PathVariable("pid") String proposalId,
            @RequestParam("amendmentNumber") int amendmentNumber,
            @RequestHeader(value = "X-User-Id") String userId,
            @RequestHeader(value = "X-User-Role") String role,
            @RequestHeader(value = "X-Tenant-Id") String tenantId) {
        return proposalSvc.acknowledgeAmendment(proposalId, amendmentNumber, userId)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }
}
