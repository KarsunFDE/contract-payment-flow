package com.karsunfde.contractflow.contractmodification.service;

import com.karsunfde.contractflow.contractmodification.audit.AuditLogger;
import com.karsunfde.contractflow.contractmodification.dto.AmendmentRequest;
import com.karsunfde.contractflow.contractmodification.model.Amendment;
import com.karsunfde.contractflow.contractmodification.model.ContractModification;
import com.karsunfde.contractflow.contractmodification.repository.AmendmentRepository;
import com.karsunfde.contractflow.contractmodification.repository.ContractModificationRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

/**
 * Amendment issuance (FAR 15.206). Workflow 2.
 *
 * Brownfield-debt items present here:
 *   - Item 2 — amendment publication writes are audit-logged via recordAsync.
 *   - Item 9 — changeSummary stored verbatim.
 *   - Item 10 — list endpoints call findByContractModificationId without re-checking
 *     the caller's agency claim against the contractModification's agency.
 */
@Service
public class AmendmentService {

    private static final Logger log = LoggerFactory.getLogger(AmendmentService.class);

    private final AmendmentRepository repo;
    private final ContractModificationRepository solRepo;
    private final AuditLogger auditLogger;

    @Autowired
    public AmendmentService(AmendmentRepository repo,
                            ContractModificationRepository solRepo,
                            AuditLogger auditLogger) {
        this.repo = repo;
        this.solRepo = solRepo;
        this.auditLogger = auditLogger;
    }

    public Optional<Amendment> issue(String contractModificationId, AmendmentRequest req, String actor) {
        Optional<ContractModification> solOpt = solRepo.findById(contractModificationId);
        if (solOpt.isEmpty()) return Optional.empty();
        ContractModification sol = solOpt.get();

        List<Amendment> existing = repo.findByContractModificationIdOrderByNumberAsc(contractModificationId);
        int nextNumber = existing.isEmpty() ? 1 : existing.get(existing.size() - 1).getNumber() + 1;

        Amendment a = new Amendment();
        a.setContractModificationId(contractModificationId);
        a.setAgencyId(sol.getAgencyId());
        a.setNumber(nextNumber);
        // ⚠ Item 9 — raw HTML stored.
        a.setChangeSummary(req.getChangeSummary());
        a.setRequiresAcknowledgement(req.isRequiresAcknowledgement());
        a.setEffectiveAt(req.getEffectiveAt() != null ? Instant.parse(req.getEffectiveAt()) : Instant.now());
        a.setCreatedAt(Instant.now());
        Amendment saved = repo.save(a);

        // ⚠ Item 2 — fire-and-forget.
        auditLogger.recordAsync("AMEND", "amendment", saved.getId(), actor, sol.getAgencyId());

        log.info("amendment issued contractModificationId={} number={} agencyId={}",
            contractModificationId, nextNumber, sol.getAgencyId());

        return Optional.of(saved);
    }

    public List<Amendment> listForContractModification(String contractModificationId) {
        // ⚠ Item 10 — does not re-check caller's agency claim.
        return repo.findByContractModificationIdOrderByNumberAsc(contractModificationId);
    }
}
