package com.karsunfde.contractflow.contractmodification;

import com.karsunfde.contractflow.contractmodification.audit.AuditLogger;
import com.karsunfde.contractflow.contractmodification.repository.UserRepository;
import com.karsunfde.contractflow.contractmodification.service.UserService;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

/**
 * Locked-failing test for pair-unique brownfield-debt item
 * `sec-bcrypt-rounds-too-low` (Pair 2 / cohort_1_pair_2_contract).
 *
 * The debt: {@link UserService}'s password encoder uses cost factor 4
 * (~1ms hash, trivially brute-forceable). Production minimum is 12
 * (~250ms, see OWASP A07; FedRAMP IA-5(1)).
 *
 * Detection: BCrypt hashes encode the cost in their prefix. Cost=4 emits
 * "$2a$04$..."; cost=12 emits "$2a$12$...". We assert the prefix.
 *
 * Lifecycle: FAILS while debt locked. PASSES after W4 Wed AI Security Day
 * modernization (encoder rounds bumped to 12+). At fix time, flip
 * docs/debt-lockfile.yml entry for sec-bcrypt-rounds-too-low from
 * locked: true -> false with the debt-touch-approved PR label.
 *
 * @see com.karsunfde.contractflow.contractmodification.service.UserService
 *      field {@code passwordEncoder}
 */
@Tag("brownfield_debt")
@Tag("brownfield_debt_pair_unique")
class BcryptRoundsTooLowDebtTest {

    @Test
    void bcryptCostFactorIsAtLeast12_DEBT_LOCKED() {
        UserRepository repo = mock(UserRepository.class);
        AuditLogger audit = mock(AuditLogger.class);
        UserService svc = new UserService(repo, audit);

        String hash = svc.hashPassword("test-password");

        // EXPECTED-AFTER-FIX: cost=12 → "$2a$12$..." (or $2b$/$2y$)
        // While debt locked: cost=4 → "$2a$04$..." → this fails.
        assertThat(hash)
            .as("BCrypt cost factor must be at least 12 per OWASP A07 + FedRAMP IA-5(1)")
            .matches("^\\$2[aby]\\$1[2-9]\\$.*|^\\$2[aby]\\$[2-9][0-9]\\$.*");
    }
}
