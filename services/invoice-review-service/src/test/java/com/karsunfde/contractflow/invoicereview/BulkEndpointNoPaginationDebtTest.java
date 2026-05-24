package com.karsunfde.contractflow.invoicereview;

import com.karsunfde.contractflow.invoicereview.controller.ContractModificationListController;
import com.karsunfde.contractflow.invoicereview.model.ContractModification;
import com.karsunfde.contractflow.invoicereview.repository.ContractModificationRepository;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Locked-failing test for pair-unique brownfield-debt item
 * `rel-bulk-endpoint-no-pagination` (Pair 2 / cohort_1_pair_2_contract).
 *
 * The debt: {@link ContractModificationListController#listAll()} returns
 * {@code repo.findAll()} with no pagination. With 100k+ contract-mod rows
 * across the lifecycle, this is an OOM trigger.
 *
 * Detection: invoke with a 2000-row repo stub and assert the returned
 * list size is either capped (<=100) or that the controller short-
 * circuits with a sentinel (e.g., throws to demand pagination params).
 *
 * Lifecycle: FAILS while debt locked. PASSES after W5 (AIOps day)
 * modernization that introduces Pageable + a hard server-side cap.
 *
 * Test-infra note: plain JUnit5 + Mockito (no @SpringBootTest needed —
 * the bug is in the controller method body, not the dispatch layer).
 * Adapted from pool sketch which proposed a live HTTP probe; lighter
 * unit-style test exercises the same invariant.
 */
@Tag("brownfield_debt")
@Tag("brownfield_debt_pair_unique")
class BulkEndpointNoPaginationDebtTest {

    @Test
    void listAllRejectsLargeQueryWithoutPagination_DEBT_LOCKED() {
        ContractModificationRepository repo = mock(ContractModificationRepository.class);
        List<ContractModification> stub = new ArrayList<>();
        for (int i = 0; i < 2000; i++) {
            ContractModification m = new ContractModification();
            m.setId("mod-" + i);
            m.setContractId("contract-" + (i % 50));
            stub.add(m);
        }
        when(repo.findAll()).thenReturn(stub);

        ContractModificationListController controller =
            new ContractModificationListController(repo);

        List<ContractModification> result = controller.listAll();

        // EXPECTED-AFTER-FIX: response is capped (Pageable defaults to <=100).
        // While debt locked: result.size() == 2000 → fails.
        assertThat(result)
            .as("listAll must page or cap large result sets (no unbounded findAll)")
            .hasSizeLessThanOrEqualTo(100);
    }
}
