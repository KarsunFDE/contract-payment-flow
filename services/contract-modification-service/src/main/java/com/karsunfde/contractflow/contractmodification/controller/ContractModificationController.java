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
 * ContractModification REST surface — covers Workflow 1 (drafting → publication),
 * Workflow 2 (Q&A + amendments), Workflow 3 (proposal intake).
 *
 * Endpoints (feature-inventory-target.md, contract-modification-service rows):
 *   POST    /api/contract-modifications
 *   GET     /api/contract-modifications
 *   GET     /api/contract-modifications/{id}
 *   PUT     /api/contract-modifications/{id}
 *   DELETE  /api/contract-modifications/{id}
 *   POST    /api/contract-modifications/{id}/publish
 *   POST    /api/contract-modifications/{id}/cancel
 *   POST    /api/contract-modifications/{id}/amendments
 *   GET     /api/contract-modifications/{id}/amendments
 *   POST    /api/contract-modifications/{id}/qa
 *   PUT     /api/contract-modifications/{id}/qa/{qnaId}/answer
 *   GET     /api/contract-modifications/{id}/qa
 *   POST    /api/contract-modifications/{id}/proposals
 *   GET     /api/contract-modifications/{id}/proposals
 *   POST    /api/contract-modifications/{id}/proposals/{pid}/acknowledge-amendment
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
    public List<ContractModification> list(@RequestHeader(value = "X-User", defaultValue = "anonymous") String actor) {
        // ⚠ Item 10 — does not filter by agency.
        return svc.listAll();
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
            @RequestHeader(value = "X-User", defaultValue = "anonymous") String actor) {
        // ⚠ Item 9 — no validation on req.description.
        ContractModification created = svc.create(req, actor);
        return ResponseEntity.ok(created);
    }

    @PutMapping("/{id}")
    public ResponseEntity<ContractModification> update(
            @PathVariable String id,
            @RequestBody ContractModificationCreateRequest req,
            @RequestHeader(value = "X-User", defaultValue = "anonymous") String actor) {
        return svc.update(id, req, actor)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(
            @PathVariable String id,
            @RequestHeader(value = "X-User", defaultValue = "anonymous") String actor) {
        boolean ok = svc.delete(id, actor);
        return ok ? ResponseEntity.noContent().build() : ResponseEntity.notFound().build();
    }

    // -------- State machine transitions (Workflow 1) --------

    @PostMapping("/{id}/publish")
    public ResponseEntity<ContractModification> publish(
            @PathVariable String id,
            @RequestHeader(value = "X-User", defaultValue = "anonymous") String actor) {
        return svc.publish(id, actor)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }

    @PostMapping("/{id}/cancel")
    public ResponseEntity<ContractModification> cancel(
            @PathVariable String id,
            @RequestHeader(value = "X-User", defaultValue = "anonymous") String actor) {
        return svc.cancel(id, actor)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }

    // -------- Amendments (Workflow 2 — FAR 15.206) --------

    @PostMapping("/{id}/amendments")
    public ResponseEntity<Amendment> issueAmendment(
            @PathVariable String id,
            @RequestBody AmendmentRequest req,
            @RequestHeader(value = "X-User", defaultValue = "anonymous") String actor) {
        return amendmentSvc.issue(id, req, actor)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }

    @GetMapping("/{id}/amendments")
    public List<Amendment> listAmendments(@PathVariable String id) {
        // ⚠ Item 10 — does not re-check caller agency.
        return amendmentSvc.listForContractModification(id);
    }

    // -------- Q&A (Workflow 2) --------

    @PostMapping("/{id}/qa")
    public ResponseEntity<Qna> submitQuestion(
            @PathVariable String id,
            @RequestBody QnaRequest req,
            @RequestHeader(value = "X-User", defaultValue = "anonymous") String actor) {
        return qnaSvc.submit(id, req, actor)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }

    @PutMapping("/{id}/qa/{qnaId}/answer")
    public ResponseEntity<Qna> answer(
            @PathVariable String id,
            @PathVariable String qnaId,
            @RequestBody QnaAnswerRequest req,
            @RequestHeader(value = "X-User", defaultValue = "anonymous") String actor) {
        return qnaSvc.answer(qnaId, req, actor)
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
            @RequestHeader(value = "X-User", defaultValue = "anonymous") String actor) {
        return proposalSvc.submit(id, req, actor)
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
            @RequestHeader(value = "X-User", defaultValue = "anonymous") String actor) {
        return proposalSvc.acknowledgeAmendment(proposalId, amendmentNumber, actor)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }
}
