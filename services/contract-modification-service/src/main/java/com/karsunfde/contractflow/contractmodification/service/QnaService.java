package com.karsunfde.contractflow.contractmodification.service;

import com.karsunfde.contractflow.contractmodification.audit.AuditLogger;
import com.karsunfde.contractflow.contractmodification.dto.QnaAnswerRequest;
import com.karsunfde.contractflow.contractmodification.dto.QnaRequest;
import com.karsunfde.contractflow.contractmodification.model.Qna;
import com.karsunfde.contractflow.contractmodification.model.ContractModification;
import com.karsunfde.contractflow.contractmodification.repository.QnaRepository;
import com.karsunfde.contractflow.contractmodification.repository.ContractModificationRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

/**
 * Vendor Q&A workflow.
 *
 * Brownfield-debt items present here:
 *   - Item 2 — Q&A state transitions audit-logged via recordAsync.
 *   - Item 9 — question + answer stored verbatim; both feed the
 *     ai-orchestrator /answer-qa prompt.
 *   - Item 10 — listForContractModification does not re-check agency.
 */
@Service
public class QnaService {

    private static final Logger log = LoggerFactory.getLogger(QnaService.class);

    private final QnaRepository repo;
    private final ContractModificationRepository solRepo;
    private final AuditLogger auditLogger;

    @Autowired
    public QnaService(QnaRepository repo, ContractModificationRepository solRepo, AuditLogger auditLogger) {
        this.repo = repo;
        this.solRepo = solRepo;
        this.auditLogger = auditLogger;
    }

    public Optional<Qna> submit(String contract_modificationId, QnaRequest req, String actor) {
        Optional<ContractModification> solOpt = solRepo.findById(contract_modificationId);
        if (solOpt.isEmpty()) return Optional.empty();
        ContractModification sol = solOpt.get();

        Qna q = new Qna();
        q.setContractModificationId(contract_modificationId);
        q.setAgencyId(sol.getAgencyId());
        // ⚠ Item 9 — raw HTML accepted.
        q.setQuestion(req.getQuestion());
        q.setVendorId(req.getVendorId());
        q.setStatus("SUBMITTED");
        q.setSubmittedAt(Instant.now());
        Qna saved = repo.save(q);

        // ⚠ Item 2 — fire-and-forget.
        auditLogger.recordAsync("QNA_SUBMIT", "qna", saved.getId(), actor, sol.getAgencyId());

        log.info("qna submitted contract_modificationId={} vendorId={}", contract_modificationId, req.getVendorId());
        return Optional.of(saved);
    }

    public Optional<Qna> answer(String qnaId, QnaAnswerRequest req, String actor) {
        return repo.findById(qnaId).map(q -> {
            // ⚠ Item 9.
            q.setAnswer(req.getAnswer());
            q.setStatus("PUBLISHED");
            q.setAnsweredAt(Instant.now());
            Qna saved = repo.save(q);
            // ⚠ Item 2.
            auditLogger.recordAsync("QNA_ANSWER", "qna", saved.getId(), actor, q.getAgencyId());
            return saved;
        });
    }

    public List<Qna> listForContractModification(String contract_modificationId) {
        // ⚠ Item 10 — does not re-check caller agency.
        return repo.findByContractModificationId(contract_modificationId);
    }
}
