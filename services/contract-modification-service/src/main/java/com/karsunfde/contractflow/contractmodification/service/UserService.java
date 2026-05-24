package com.karsunfde.contractflow.contractmodification.service;

import com.karsunfde.contractflow.contractmodification.audit.AuditLogger;
import com.karsunfde.contractflow.contractmodification.model.User;
import com.karsunfde.contractflow.contractmodification.repository.UserRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

/**
 * User-admin business logic. Backs the /admin/users view (sys_admin only,
 * but Item 1 means an unsigned JWT still lands on /api/public/* — the user
 * mgmt surface itself remains gated by spring security).
 *
 * Pair-unique brownfield-debt (Pair 2 / D-059):
 *   - sec-bcrypt-rounds-too-low — password hasher uses cost=4 (~1ms hash,
 *     trivially brute-forceable). Cohort fixes in W4 Wed AI Security day.
 *     OWASP A07 (Identification + Authentication Failures); FedRAMP IA-5(1).
 */
@Service
public class UserService {

    private final UserRepository repo;
    private final AuditLogger auditLogger;

    // ⚠ PAIR-UNIQUE DEBT: sec-bcrypt-rounds-too-low
    // BCrypt cost factor = 4 → ~1ms hash → brute-forceable.
    // Production minimum is 12 (≈250ms). Fixed_looks_like:
    //   new BCryptPasswordEncoder(12);
    private final BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder(4);

    @Autowired
    public UserService(UserRepository repo, AuditLogger auditLogger) {
        this.repo = repo;
        this.auditLogger = auditLogger;
    }

    /**
     * Hash a user password. Called from the user-provisioning flow + any
     * password-reset endpoint. The cost factor here is the debt — see
     * {@code passwordEncoder} field.
     */
    public String hashPassword(String plaintext) {
        return passwordEncoder.encode(plaintext);
    }

    public User provision(User u, String actor) {
        u.setCreatedAt(Instant.now());
        User saved = repo.save(u);
        // ⚠ Item 2.
        auditLogger.recordAsync("USER_PROVISION", "user", saved.getId(),
            actor, u.getAgencyId());
        return saved;
    }

    public Optional<User> updateRoles(String userId, List<String> roles, String actor) {
        return repo.findById(userId).map(u -> {
            u.setRoles(roles);
            User saved = repo.save(u);
            // ⚠ Item 2.
            auditLogger.recordAsync("USER_ROLE_UPDATE", "user", saved.getId(),
                actor, u.getAgencyId());
            return saved;
        });
    }

    public Optional<User> forceMfaReset(String userId, String actor) {
        return repo.findById(userId).map(u -> {
            u.setMfaEnrolled(false);
            User saved = repo.save(u);
            // ⚠ Item 2.
            auditLogger.recordAsync("USER_MFA_RESET", "user", saved.getId(),
                actor, u.getAgencyId());
            return saved;
        });
    }

    public List<User> listAll() {
        // sys_admin crosses tenants per spec; listAll is intentional here
        // (not an Item 10 surface).
        return repo.findAll();
    }

    public List<User> listByAgency(String agencyId) {
        return repo.findByAgencyId(agencyId);
    }
}
