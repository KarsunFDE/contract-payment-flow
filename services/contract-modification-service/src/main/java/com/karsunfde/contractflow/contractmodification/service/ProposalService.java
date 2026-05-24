package com.karsunfde.contractflow.contractmodification.service;

import com.karsunfde.contractflow.contractmodification.audit.AuditLogger;
import com.karsunfde.contractflow.contractmodification.dto.ProposalSubmitRequest;
import com.karsunfde.contractflow.contractmodification.model.Proposal;
import com.karsunfde.contractflow.contractmodification.model.ContractModification;
import com.karsunfde.contractflow.contractmodification.repository.ProposalRepository;
import com.karsunfde.contractflow.contractmodification.repository.ContractModificationRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

/**
 * Proposal intake + sealed-lockbox workflow (Workflow 3).
 *
 * Brownfield-debt items present here:
 *   - Item 2 — unseal is multi-step; race with crash can leave the unseal
 *     event un-audited.
 *   - Item 10 — list endpoints do not enforce per-vendor agency boundary.
 */
@Service
public class ProposalService {

    private static final Logger log = LoggerFactory.getLogger(ProposalService.class);

    private final ProposalRepository repo;
    private final ContractModificationRepository solRepo;
    private final AuditLogger auditLogger;

    @Autowired
    public ProposalService(ProposalRepository repo,
                           ContractModificationRepository solRepo,
                           AuditLogger auditLogger) {
        this.repo = repo;
        this.solRepo = solRepo;
        this.auditLogger = auditLogger;
    }

    public Optional<Proposal> submit(String contract_modificationId, ProposalSubmitRequest req, String actor) {
        Optional<ContractModification> solOpt = solRepo.findById(contract_modificationId);
        if (solOpt.isEmpty()) return Optional.empty();
        ContractModification sol = solOpt.get();

        Proposal p = new Proposal();
        p.setContractModificationId(contract_modificationId);
        p.setAgencyId(sol.getAgencyId());
        p.setVendorId(req.getVendorId());
        p.setVolumes(req.getVolumes());
        p.setAcknowledgedAmendments(req.getAcknowledgedAmendments());
        p.setStatus("SEALED");
        p.setSubmittedAt(Instant.now());
        p.setSealedUntil(sol.getClosingAt());
        Proposal saved = repo.save(p);

        // ⚠ Item 2.
        auditLogger.recordAsync("PROPOSAL_SUBMIT", "proposal", saved.getId(),
            actor, sol.getAgencyId());

        log.info("proposal submitted contract_modificationId={} vendorId={}",
            contract_modificationId, req.getVendorId());
        return Optional.of(saved);
    }

    /**
     * Vendor-side endpoint to acknowledge an amendment for a proposal-in-progress
     * (FAR 15.206 — vendors must re-acknowledge after scope-changing amendments).
     */
    public Optional<Proposal> acknowledgeAmendment(String proposalId, int amendmentNumber, String actor) {
        return repo.findById(proposalId).map(p -> {
            if (!p.getAcknowledgedAmendments().contains(amendmentNumber)) {
                p.getAcknowledgedAmendments().add(amendmentNumber);
            }
            Proposal saved = repo.save(p);
            // ⚠ Item 2.
            auditLogger.recordAsync("PROPOSAL_ACK_AMEND", "proposal",
                saved.getId(), actor, p.getAgencyId());
            return saved;
        });
    }

    public List<Proposal> listForContractModification(String contract_modificationId) {
        // ⚠ Item 10 — should re-check the caller's agency.
        return repo.findByContractModificationId(contract_modificationId);
    }

    public List<Proposal> listForVendor(String vendorId) {
        return repo.findByVendorId(vendorId);
    }
}
