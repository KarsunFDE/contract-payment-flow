package com.karsunfde.contractflow.contractmodification;

import com.karsunfde.contractflow.contractmodification.audit.AuditLogger;
import com.karsunfde.contractflow.contractmodification.repository.ContractModificationRepository;
import com.karsunfde.contractflow.contractmodification.service.ContractModificationService;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Brownfield-debt item 10 (no-multi-tenant-boundary) — FIXED week 4
 * (was scheduled W2-Wed; multi-tenant-retrieval-boundary teaching anchor).
 *
 * WAS: ContractModificationService.listAll() called repo.findAll() — an
 * unfiltered cross-agency query that leaked contract modifications across
 * ALL agencies.
 *
 * NOW (post-fix invariant asserted below): the authenticated/tenant-scoped
 * listing routes through repo.findByAgencyId(agency) and never invokes
 * repo.findAll(). The no-arg svc.listAll() remains intentionally cross-tenant
 * ONLY for the public SAM.gov-style opportunities surface.
 *
 * Single Mockito verify() assertion — the fixed state is observable by
 * watching which repository method the service calls.
 */
@Tag("brownfield_debt")
@Tag("brownfield_debt_10")
class MultiTenantBoundaryDebtTest {

    @Test
    void listAll_tenantScoped_filters_by_agency_and_never_calls_findAll() {
        ContractModificationRepository repo = mock(ContractModificationRepository.class);
        AuditLogger audit = mock(AuditLogger.class);
        when(repo.findByAgencyId(anyString())).thenReturn(List.of());
        ContractModificationService svc = new ContractModificationService(repo, audit);

        svc.listAll("AGENCY-X");

        verify(repo).findByAgencyId("AGENCY-X");
        verify(repo, never()).findAll();
    }
}
