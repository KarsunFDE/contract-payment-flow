package com.karsunfde.contractflow.invoicereview.service;

import com.karsunfde.contractflow.invoicereview.audit.EvalAuditLogger;
import com.karsunfde.contractflow.invoicereview.client.AiOrchestratorClient;
import com.karsunfde.contractflow.invoicereview.client.ContractModificationClient;
import com.karsunfde.contractflow.invoicereview.model.InvoiceReview;
import com.karsunfde.contractflow.invoicereview.model.InvoiceReviewScore;
import com.karsunfde.contractflow.invoicereview.repository.InvoiceReviewRepository;
import com.karsunfde.contractflow.invoicereview.repository.InvoiceReviewScoreRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.*;
import java.util.stream.Collectors;

/**
 * Workflow 4 — invoice_review → consensus → source selection → award (pre-award).
 *
 * Brownfield-debt items reinforced:
 *   - Item 3 — calls contract-modification-service for each proposal text via
 *     ContractModificationClient (no circuit breaker).
 *   - Item 2 — state transitions audit-logged via async.
 *   - Item 4 reinforcement — SSDD draft response from ai-orchestrator goes
 *     straight back; no structured-output schema enforcement.
 */
@Service
public class InvoiceReviewService {

    private static final Logger log = LoggerFactory.getLogger(InvoiceReviewService.class);

    private final InvoiceReviewRepository evalRepo;
    private final InvoiceReviewScoreRepository scoreRepo;
    private final ContractModificationClient contract_modificationClient;
    private final AiOrchestratorClient aiClient;
    private final EvalAuditLogger auditLogger;

    @Autowired
    public InvoiceReviewService(InvoiceReviewRepository evalRepo,
                             InvoiceReviewScoreRepository scoreRepo,
                             ContractModificationClient contract_modificationClient,
                             AiOrchestratorClient aiClient,
                             EvalAuditLogger auditLogger) {
        this.evalRepo = evalRepo;
        this.scoreRepo = scoreRepo;
        this.contractmodificationClient = contract_modificationClient;
        this.aiClient = aiClient;
        this.auditLogger = auditLogger;
    }

    public InvoiceReview create(String contract_modificationId, String agencyId, String actor) {
        InvoiceReview e = new InvoiceReview();
        e.setContractModificationId(contract_modificationId);
        e.setAgencyId(agencyId);
        e.setState("OPEN");
        e.setCreatedAt(Instant.now());
        InvoiceReview saved = evalRepo.save(e);
        auditLogger.recordAsync("EVAL_CREATE", "invoice_review", saved.getId(), actor, agencyId);
        return saved;
    }

    public Optional<InvoiceReview> findById(String id) {
        return evalRepo.findById(id);
    }

    public Optional<InvoiceReview> assignPanel(String invoice_reviewId, List<String> panelMembers, String actor) {
        return evalRepo.findById(invoice_reviewId).map(e -> {
            e.setPanelMembers(panelMembers);
            e.setState("PANEL_ASSIGNED");
            InvoiceReview saved = evalRepo.save(e);
            auditLogger.recordAsync("EVAL_PANEL_ASSIGN", "invoice_review", saved.getId(),
                actor, e.getAgencyId());
            return saved;
        });
    }

    public Optional<InvoiceReviewScore> submitScore(String invoice_reviewId, InvoiceReviewScore in, String actor) {
        Optional<InvoiceReview> eOpt = evalRepo.findById(invoice_reviewId);
        if (eOpt.isEmpty()) return Optional.empty();
        InvoiceReview e = eOpt.get();

        // ⚠ Item 3 — fetches proposal context from contract-modification-service for
        // each score submission. No circuit breaker; under TEP-week load
        // this is the thread-exhaustion reproducer.
        Map<String, Object> proposal = contract_modificationClient.getContractModification(in.getProposalId());
        log.info("score submission invoice_reviewId={} proposalId={} proposal-loaded={}",
            invoice_reviewId, in.getProposalId(), proposal != null);

        in.setInvoiceReviewId(invoice_reviewId);
        in.setScoredAt(Instant.now());
        InvoiceReviewScore saved = scoreRepo.save(in);

        // ⚠ Item 2.
        auditLogger.recordAsync("EVAL_SCORE", "score", saved.getId(),
            actor, e.getAgencyId());

        // Promote invoice_review state on first score.
        if (!"SCORING".equals(e.getState())) {
            e.setState("SCORING");
            evalRepo.save(e);
        }
        return Optional.of(saved);
    }

    /** Aggregate panel consensus per proposal × factor. */
    public Map<String, Map<String, Double>> consensus(String invoice_reviewId) {
        List<InvoiceReviewScore> scores = scoreRepo.findByInvoiceReviewId(invoice_reviewId);
        Map<String, List<InvoiceReviewScore>> byProposal = scores.stream()
            .collect(Collectors.groupingBy(InvoiceReviewScore::getProposalId));
        Map<String, Map<String, Double>> out = new LinkedHashMap<>();
        for (Map.Entry<String, List<InvoiceReviewScore>> p : byProposal.entrySet()) {
            Map<String, Double> byFactor = p.getValue().stream()
                .collect(Collectors.groupingBy(
                    InvoiceReviewScore::getFactorId,
                    Collectors.averagingInt(InvoiceReviewScore::getScore)));
            out.put(p.getKey(), byFactor);
        }
        return out;
    }

    /** Generate Source Selection Decision Document via ai-orchestrator. */
    public Optional<Map<String, Object>> draftSsdd(String invoice_reviewId, String actor) {
        return evalRepo.findById(invoice_reviewId).map(e -> {
            // ⚠ Item 4 reinforcement — raw response returned; no schema check.
            Map<String, Object> resp = aiClient.draftSsdd(invoice_reviewId);
            e.setState("CONSENSUS");
            e.setConsensusAt(Instant.now());
            // Store doc id placeholder from response if present.
            if (resp != null && resp.get("clause_id") != null) {
                e.setSsddDocId(resp.get("clause_id").toString());
            }
            evalRepo.save(e);
            auditLogger.recordAsync("SSDD_DRAFT", "invoice_review", invoice_reviewId,
                actor, e.getAgencyId());
            return resp;
        });
    }
}
