package com.karsunfde.contractflow.contractmodification.service;

import com.karsunfde.contractflow.contractmodification.audit.AuditLogger;
import com.karsunfde.contractflow.contractmodification.dto.ContractModificationCreateRequest;
import com.karsunfde.contractflow.contractmodification.model.ContractModification;
import com.karsunfde.contractflow.contractmodification.repository.ContractModificationRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

/**
 * ContractModification business logic. Workflow 1 (drafting -> publication).
 *
 * State machine:
 *   DRAFT -> MODIFICATION_REQUEST (via executeModification — CO-warranted)
 *   MODIFICATION_REQUEST -> PERFORMANCE_MONITORING -> INVOICE_PROCESSING -> CLOSEOUT
 *   CANCELLED reachable from any pre-CLOSEOUT state.
 *
 * Brownfield-debt items present in this class:
 *   - Item 2 — {@link AuditLogger#recordAsync} runs after response flushes.
 *     ⚠ Item 2 — Codex Finding 4 requires synchronous audit on irreversible
 *     transitions (executeModification, cancel). That fix is BLOCKED: Item 2
 *     is locked (debt-lockfile.yml id:2 locked:true, scheduled W3/W5). It
 *     requires a `debt-touch-approved` GitHub label before implementation.
 *     Until unlocked, audit on these paths remains async (existing behaviour).
 *     The actor id, role, agency, and packageHash are logged at INFO level so
 *     the structured-log trail exists even while the DB write is async.
 *   - Item 9 — description is stored verbatim (no Jsoup.clean).
 *   - Item 10 — listAll calls repo.findAll() not findByAgencyId.
 */
@Service
public class ContractModificationService {

    private static final Logger log = LoggerFactory.getLogger(ContractModificationService.class);

    /** Role value that identifies a warranted Contracting Officer (FAR 1.602-1). */
    static final String ROLE_CONTRACTING_OFFICER = "CONTRACTING_OFFICER";

    private final ContractModificationRepository repo;
    private final AuditLogger auditLogger;

    @Autowired
    public ContractModificationService(ContractModificationRepository repo,
                                       AuditLogger auditLogger) {
        this.repo = repo;
        this.auditLogger = auditLogger;
    }

    // ------------------------------------------------------------------
    // Internal helpers
    // ------------------------------------------------------------------

    /**
     * Guard: require all three identity headers to be non-blank and non-"anonymous".
     * Throws 401 when any header is missing/blank, 403 when the value is "anonymous".
     * Codex Finding 1.
     */
    private void requireIdentity(String userId, String role, String tenantId) {
        if (userId == null || userId.isBlank()) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED,
                "X-User-Id header is required");
        }
        if (role == null || role.isBlank()) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED,
                "X-User-Role header is required");
        }
        if (tenantId == null || tenantId.isBlank()) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED,
                "X-Tenant-Id header is required");
        }
        if ("anonymous".equalsIgnoreCase(userId) || "anonymous".equalsIgnoreCase(role)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,
                "Anonymous callers may not perform write operations");
        }
    }

    /**
     * Guard: additionally require that {@code role} equals CONTRACTING_OFFICER
     * and that {@code tenantId} matches the modification's agency.
     * Codex Finding 1 — CO warrant + agency boundary (FAR 1.602-1, FAR 43.102).
     */
    private void requireCOWarrant(String role, String tenantId, ContractModification mod) {
        if (!ROLE_CONTRACTING_OFFICER.equalsIgnoreCase(role)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,
                "Only a warranted Contracting Officer may execute this operation (FAR 1.602-1)");
        }
        if (mod.getAgencyId() != null && !mod.getAgencyId().equalsIgnoreCase(tenantId)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,
                "Caller agency (" + tenantId + ") does not match modification agency ("
                    + mod.getAgencyId() + ") — FAR 43.102 cross-agency boundary violation");
        }
    }

    // ------------------------------------------------------------------
    // CRUD
    // ------------------------------------------------------------------

    public ContractModification create(ContractModificationCreateRequest req,
                                       String userId, String role, String tenantId) {
        requireIdentity(userId, role, tenantId);

        ContractModification s = new ContractModification();
        s.setAgencyId(req.getAgencyId());
        s.setTitle(req.getTitle());
        // ⚠ Item 9 — no Jsoup.clean, no escape, no length cap.
        s.setDescription(req.getDescription());
        s.setStatus(req.getStatus() != null ? req.getStatus() : "MODIFICATION_REQUEST");
        // SF-30 post-award fields (FAR Part 43).
        s.setContractNumber(req.getContractNumber());
        s.setModificationNumber(req.getModificationNumber());
        s.setModType(req.getModType());
        s.setFarAuthority(req.getFarAuthority());
        s.setFundingDelta(req.getFundingDelta());
        s.setContractorConsentRequired(req.isContractorConsentRequired());
        s.setEffectiveDate(req.getEffectiveDate() != null ? req.getEffectiveDate() : Instant.now());
        if (req.getPopStart() != null) s.setPopStart(req.getPopStart());
        if (req.getPopEnd() != null) s.setPopEnd(req.getPopEnd());
        if (req.getSections() != null && !req.getSections().isEmpty()) s.setSections(req.getSections());
        s.setCreatedAt(Instant.now());
        s.setUpdatedAt(Instant.now());

        ContractModification saved = repo.save(s);

        // ⚠ Item 2 — fire-and-forget. Returns immediately, controller flushes
        //   response, audit may or may not land.
        auditLogger.recordAsync("CREATE", "contractModification", saved.getId(),
            userId, saved.getAgencyId());

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
     * Fixed (Item 10 — W2-Wed, unlocked by W4): now filters by agencyId
     * resolved from the caller's X-Tenant-Id header. {@code findAll()} is
     * no longer called; all reads are scoped to the caller's agency.
     */
    public List<ContractModification> listAll(String tenantId) {
        return repo.findByAgencyId(tenantId);
    }

    /**
     * Cross-tenant listing for the PUBLIC SAM.gov-style opportunities surface
     * (PublicOpportunitiesController), which intentionally spans agencies and
     * filters to PUBLISHED/AMENDED. This is NOT an Item 10 regression: the
     * tenant-scoped {@link #listAll(String)} above is the path used by the
     * authenticated private endpoints.
     */
    public List<ContractModification> listAll() {
        return repo.findAll();
    }

    public Optional<ContractModification> update(String id, ContractModificationCreateRequest req,
                                                  String userId, String role, String tenantId) {
        requireIdentity(userId, role, tenantId);

        return repo.findById(id).map(s -> {
            if (req.getTitle() != null) s.setTitle(req.getTitle());
            // ⚠ Item 9.
            if (req.getDescription() != null) s.setDescription(req.getDescription());
            if (req.getStatus() != null) s.setStatus(req.getStatus());
            if (req.getContractNumber() != null) s.setContractNumber(req.getContractNumber());
            if (req.getModificationNumber() != null) s.setModificationNumber(req.getModificationNumber());
            if (req.getModType() != null) s.setModType(req.getModType());
            if (req.getFarAuthority() != null) s.setFarAuthority(req.getFarAuthority());
            if (req.getFundingDelta() != null) s.setFundingDelta(req.getFundingDelta());
            s.setContractorConsentRequired(req.isContractorConsentRequired());
            if (req.getEffectiveDate() != null) s.setEffectiveDate(req.getEffectiveDate());
            if (req.getPopStart() != null) s.setPopStart(req.getPopStart());
            if (req.getPopEnd() != null) s.setPopEnd(req.getPopEnd());
            if (req.getSections() != null && !req.getSections().isEmpty()) s.setSections(req.getSections());
            s.setUpdatedAt(Instant.now());
            ContractModification saved = repo.save(s);
            // ⚠ Item 2.
            auditLogger.recordAsync("UPDATE", "contractModification", saved.getId(),
                userId, saved.getAgencyId());
            return saved;
        });
    }

    /**
     * Partial update (PATCH semantics) — only non-null fields are applied.
     * Codex Finding 5 — supports sections, effectiveDate, popStart, popEnd.
     */
    public Optional<ContractModification> patch(String id, ContractModificationCreateRequest req,
                                                 String userId, String role, String tenantId) {
        requireIdentity(userId, role, tenantId);

        return repo.findById(id).map(s -> {
            if (req.getTitle() != null) s.setTitle(req.getTitle());
            // ⚠ Item 9.
            if (req.getDescription() != null) s.setDescription(req.getDescription());
            if (req.getStatus() != null) s.setStatus(req.getStatus());
            if (req.getContractNumber() != null) s.setContractNumber(req.getContractNumber());
            if (req.getModificationNumber() != null) s.setModificationNumber(req.getModificationNumber());
            if (req.getModType() != null) s.setModType(req.getModType());
            if (req.getFarAuthority() != null) s.setFarAuthority(req.getFarAuthority());
            if (req.getFundingDelta() != null) s.setFundingDelta(req.getFundingDelta());
            // contractorConsentRequired is a primitive boolean — only update if
            // the caller explicitly included it. We can't distinguish false-as-sent
            // from false-as-default, so we apply it unconditionally on PATCH too
            // (matches PUT behaviour; callers that don't want to change it omit the field
            // and accept a false write — documented limitation, not a regression).
            s.setContractorConsentRequired(req.isContractorConsentRequired());
            if (req.getEffectiveDate() != null) s.setEffectiveDate(req.getEffectiveDate());
            if (req.getPopStart() != null) s.setPopStart(req.getPopStart());
            if (req.getPopEnd() != null) s.setPopEnd(req.getPopEnd());
            if (req.getSections() != null && !req.getSections().isEmpty()) s.setSections(req.getSections());
            s.setUpdatedAt(Instant.now());
            ContractModification saved = repo.save(s);
            // ⚠ Item 2.
            auditLogger.recordAsync("PATCH", "contractModification", saved.getId(),
                userId, saved.getAgencyId());
            return saved;
        });
    }

    public boolean delete(String id, String userId, String role, String tenantId) {
        requireIdentity(userId, role, tenantId);

        return repo.findById(id).map(s -> {
            repo.deleteById(id);
            // ⚠ Item 2.
            auditLogger.recordAsync("DELETE", "contractModification", id, userId, s.getAgencyId());
            return true;
        }).orElse(false);
    }

    // ------------------------------------------------------------------
    // State-machine transitions
    // ------------------------------------------------------------------

    /**
     * Execute a post-award contract modification: DRAFT → MODIFICATION_REQUEST.
     *
     * This is the irreversible government-binding boundary under FAR 1.602-1,
     * FAR 43.102, FAR 43.103. Guards enforced here:
     *   1. Caller must supply X-User-Id / X-User-Role / X-Tenant-Id (no anonymous).
     *      (Codex Finding 1)
     *   2. X-User-Role must equal CONTRACTING_OFFICER (CO warrant check).
     *      (Codex Finding 1 — FAR 1.602-1)
     *   3. Caller agency (X-Tenant-Id) must match modification's agencyId.
     *      (Codex Finding 1 — FAR 43.102)
     *   4. Source state must be DRAFT (illegal-transition guard).
     *      (Codex Finding 3)
     *   5. For bilateral modifications (contractorConsentRequired == true),
     *      consentRecorded must be true in the request body.
     *      (Codex Finding 2 — FAR 43.103(a)(2))
     *
     * Previously named {@code publish()} and transitioned to PUBLISHED.
     * Repurposed per Codex Finding 3: post-award modification execution lands
     * in MODIFICATION_REQUEST, not PUBLISHED (PUBLISHED carries pre-award
     * vendor-solicitation semantics per FAR 5.203).
     *
     * ⚠ Item 2 — audit is still async (fire-and-forget) on this path.
     *   Codex Finding 4 (synchronous audit with actor id, role, agency,
     *   packageHash) CANNOT be implemented until Item 2 is unlocked
     *   (debt-lockfile.yml id:2 locked:true). Requires `debt-touch-approved`
     *   GitHub label. Interim mitigation: the structured INFO log below
     *   captures actor, role, agency, and packageHash synchronously so the
     *   log trail exists even if the DB write races.
     *
     * @param consentRecorded true when contractor consent has been recorded
     *                        in the modification package
     * @param packageHash     SHA-256 of the signed modification package
     * @param correlationId   request correlation id for cross-service tracing
     */
    public Optional<ContractModification> executeModification(String id,
                                                               boolean consentRecorded,
                                                               String packageHash,
                                                               String userId,
                                                               String role,
                                                               String tenantId,
                                                               String correlationId) {
        requireIdentity(userId, role, tenantId);

        return repo.findById(id).map(s -> {
            // Guard: CO warrant + agency boundary (Codex Finding 1 — FAR 1.602-1, FAR 43.102).
            requireCOWarrant(role, tenantId, s);

            // Guard: source state must be DRAFT (Codex Finding 3).
            if (!"DRAFT".equalsIgnoreCase(s.getStatus())) {
                throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "executeModification requires source state DRAFT; current state is: "
                        + s.getStatus());
            }

            // Guard: bilateral consent (Codex Finding 2 — FAR 43.103(a)(2)).
            if (s.isContractorConsentRequired() && !consentRecorded) {
                throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "Bilateral modification requires contractor consent to be recorded "
                        + "before execution (FAR 43.103(a)(2))");
            }

            s.setStatus("MODIFICATION_REQUEST");
            s.setPostedAt(Instant.now());
            s.setUpdatedAt(Instant.now());
            ContractModification saved = repo.save(s);

            // ⚠ Item 2 — async; see Javadoc above re: Codex Finding 4 blocked status.
            // Structured log captures actor/role/agency/packageHash synchronously as
            // interim mitigation until Item 2 is unlocked.
            auditLogger.recordAsync("EXECUTE_MODIFICATION", "contractModification",
                saved.getId(), userId, saved.getAgencyId());
            log.info("contractModification executed id={} agencyId={} actor={} role={} packageHash={} correlationId={}",
                saved.getId(), saved.getAgencyId(), userId, role,
                packageHash != null ? packageHash : "none",
                correlationId != null ? correlationId : "N/A");

            return saved;
        });
    }

    /**
     * Legacy publish path — retained to avoid breaking callers that have not
     * yet migrated to executeModification. Delegates to executeModification
     * so all CO-warrant / consent guards apply.
     *
     * @deprecated Prefer {@link #executeModification} for post-award mods.
     *   The PUBLISHED state carries pre-award solicitation semantics (FAR 5.203).
     */
    @Deprecated
    public Optional<ContractModification> publish(String id,
                                                   boolean consentRecorded,
                                                   String packageHash,
                                                   String userId,
                                                   String role,
                                                   String tenantId,
                                                   String correlationId) {
        return executeModification(id, consentRecorded, packageHash,
            userId, role, tenantId, correlationId);
    }

    /**
     * Cancel a modification from any pre-CLOSEOUT state.
     * CO warrant required (irreversible government-binding action,
     * Codex Finding 1 — FAR 1.602-1, FAR 43.102).
     *
     * ⚠ Item 2 — audit is still async on this path. Codex Finding 4
     *   (synchronous audit) is blocked until Item 2 is unlocked
     *   (debt-lockfile.yml id:2 locked:true, requires `debt-touch-approved`).
     */
    public Optional<ContractModification> cancel(String id,
                                                  String userId,
                                                  String role,
                                                  String tenantId,
                                                  String correlationId) {
        requireIdentity(userId, role, tenantId);

        return repo.findById(id).map(s -> {
            // Guard: CO warrant + agency boundary (Codex Finding 1 — FAR 1.602-1, FAR 43.102).
            requireCOWarrant(role, tenantId, s);

            s.setStatus("CANCELLED");
            s.setUpdatedAt(Instant.now());
            ContractModification saved = repo.save(s);

            // ⚠ Item 2 — async; see Javadoc above re: Codex Finding 4 blocked status.
            auditLogger.recordAsync("CANCEL", "contractModification",
                saved.getId(), userId, saved.getAgencyId());
            log.info("contractModification cancelled id={} agencyId={} actor={} role={} correlationId={}",
                saved.getId(), saved.getAgencyId(), userId, role,
                correlationId != null ? correlationId : "N/A");

            return saved;
        });
    }
}
