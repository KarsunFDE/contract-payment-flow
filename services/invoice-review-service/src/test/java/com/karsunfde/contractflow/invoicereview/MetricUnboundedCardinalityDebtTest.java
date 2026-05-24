package com.karsunfde.contractflow.invoicereview;

import com.karsunfde.contractflow.invoicereview.metrics.ContractModificationMetrics;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;

import java.util.stream.IntStream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Locked-failing test for pair-unique brownfield-debt item
 * `obs-metric-unbounded-cardinality` (Pair 2 / cohort_1_pair_2_contract).
 *
 * The debt: {@link ContractModificationMetrics#recordReview(String, String)}
 * labels the counter with {@code user_id} — unbounded cardinality.
 *
 * Detection: emit 10k unique user-ids and assert that the label set on
 * the recorded counter does NOT contain "user_id". A fixed implementation
 * uses bounded labels (tenant + outcome enum).
 *
 * Lifecycle: FAILS while debt locked (label "user_id" is present on the
 * counter). PASSES after W5 modernization that drops the user_id label.
 *
 * Test-infra note: SimpleMeterRegistry is in-memory; no Datadog needed.
 */
@Tag("brownfield_debt")
@Tag("brownfield_debt_pair_unique")
class MetricUnboundedCardinalityDebtTest {

    @Test
    void counterCardinalityIsBounded_DEBT_LOCKED() {
        SimpleMeterRegistry registry = new SimpleMeterRegistry();
        ContractModificationMetrics metrics = new ContractModificationMetrics(registry);

        IntStream.range(0, 10_000).forEach(i ->
            metrics.recordReview("user-" + i, "tenant-a")
        );

        var labelKeys = registry.find("contractModification.reviewed").meters().stream()
            .flatMap(m -> m.getId().getTags().stream())
            .map(io.micrometer.core.instrument.Tag::getKey)
            .distinct()
            .toList();

        // EXPECTED-AFTER-FIX: user_id is not a label. Use tenant + outcome enum.
        // While debt locked: user_id is present → this fails.
        assertThat(labelKeys)
            .as("counter must not be labeled with unbounded user_id")
            .doesNotContain("user_id");
    }
}
