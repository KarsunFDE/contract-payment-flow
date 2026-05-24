package com.karsunfde.contractflow.contractmodification.service;

import com.karsunfde.contractflow.contractmodification.audit.AuditLogger;
import com.karsunfde.contractflow.contractmodification.dto.ContractModificationCreateRequest;
import com.karsunfde.contractflow.contractmodification.model.ContractModification;
import com.karsunfde.contractflow.contractmodification.repository.ContractModificationRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

/**
 * ContractModification business logic. Workflow 1 (drafting -> publication).
 *
 * State machine:
 *   DRAFT -> INTERNAL_REVIEW -> READY_TO_PUBLISH -> PUBLISHED -> (AMENDED)* -> CLOSED
 *   CANCELLED reachable from any pre-PUBLISHED state.
 *
 * Brownfield-debt items present in this class:
 *   - Item 2 — {@link AuditLogger#recordAsync} runs after response flushes.
 *   - Item 9 — description is stored verbatim (no Jsoup.clean).
 *   - Item 10 — listAll calls repo.findAll() not findByAgencyId.
 */
@Service
public class ContractModificationService {

    private static final Logger log = LoggerFactory.getLogger(ContractModificationService.class);

    private final ContractModificationRepository repo;
    private final AuditLogger auditLogger;

    @Autowired
    public ContractModificationService(ContractModificationRepository repo, AuditLogger auditLogger) {
        this.repo = repo;
        this.auditLogger = auditLogger;
    }

    public ContractModification create(ContractModificationCreateRequest req, String actor) {
        ContractModification s = new ContractModification();
        s.setAgencyId(req.getAgencyId());
        s.setTitle(req.getTitle());
        // ⚠ Item 9 — no Jsoup.clean, no escape, no length cap.
        s.setDescription(req.getDescription());
        s.setStatus(req.getStatus() != null ? req.getStatus() : "DRAFT");
        s.setCreatedAt(Instant.now());
        s.setUpdatedAt(Instant.now());

        ContractModification saved = repo.save(s);

        // ⚠ Item 2 — fire-and-forget. Returns immediately, controller flushes
        //   response, audit may or may not land.
        auditLogger.recordAsync("CREATE", "contractModification", saved.getId(),
            actor, saved.getAgencyId());

        log.info("contractModification created id={} agencyId={} correlationId=N/A",
            saved.getId(), saved.getAgencyId());

        return saved;
    }

    public Optional<ContractModification> findById(String id) {
        return repo.findById(id);
    }

    /**
     * ⚠ Item 10 — returns contractModifications across ALL agencies. The
     * {@code findByAgencyId} method exists on the repository but isn't
     * called from anywhere.
     */
    public List<ContractModification> listAll() {
        return repo.findAll();
    }

    public Optional<ContractModification> update(String id, ContractModificationCreateRequest req, String actor) {
        return repo.findById(id).map(s -> {
            s.setTitle(req.getTitle());
            // ⚠ Item 9.
            s.setDescription(req.getDescription());
            if (req.getStatus() != null) s.setStatus(req.getStatus());
            s.setUpdatedAt(Instant.now());
            ContractModification saved = repo.save(s);
            auditLogger.recordAsync("UPDATE", "contractModification", saved.getId(),
                actor, saved.getAgencyId());
            return saved;
        });
    }

    public boolean delete(String id, String actor) {
        return repo.findById(id).map(s -> {
            repo.deleteById(id);
            auditLogger.recordAsync("DELETE", "contractModification", id, actor, s.getAgencyId());
            return true;
        }).orElse(false);
    }

    /**
     * Transition DRAFT/INTERNAL_REVIEW/READY_TO_PUBLISH -> PUBLISHED.
     * FAR 5.203 publication. ⚠ Item 2 — publish event audit-logged async.
     */
    public Optional<ContractModification> publish(String id, String actor) {
        return repo.findById(id).map(s -> {
            s.setStatus("PUBLISHED");
            s.setPostedAt(Instant.now());
            s.setUpdatedAt(Instant.now());
            ContractModification saved = repo.save(s);
            // ⚠ Item 2.
            auditLogger.recordAsync("PUBLISH", "contractModification", saved.getId(),
                actor, saved.getAgencyId());
            log.info("contractModification published id={} agencyId={}",
                saved.getId(), saved.getAgencyId());
            return saved;
        });
    }

    public Optional<ContractModification> cancel(String id, String actor) {
        return repo.findById(id).map(s -> {
            s.setStatus("CANCELLED");
            s.setUpdatedAt(Instant.now());
            ContractModification saved = repo.save(s);
            // ⚠ Item 2.
            auditLogger.recordAsync("CANCEL", "contractModification", saved.getId(),
                actor, saved.getAgencyId());
            return saved;
        });
    }
}
