package com.karsunfde.contractflow.invoicereview.metrics;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Tag;
import io.micrometer.core.instrument.Tags;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * Operational metrics for contract-modification review events.
 *
 * Pair-unique brownfield-debt (Pair 2 / D-059):
 *   - obs-metric-unbounded-cardinality — review counter is labeled with
 *     {@code user_id}, which is unbounded. With 50k+ users across the
 *     contract-administration audience (CORs, COs, vendors, DCAA),
 *     this explodes Prometheus/Datadog cardinality and is a classic
 *     cost-attack pattern. Cohort fixes in W5 (AIOps day) — bound to
 *     tenant + a bucketed outcome enum.
 *
 * In acquire-gov this component does not exist; injected fresh per the
 * pair-brownfield-generator distribution recipe.
 */
@Component
public class ContractModificationMetrics {

    private final MeterRegistry meterRegistry;

    @Autowired
    public ContractModificationMetrics(MeterRegistry meterRegistry) {
        this.meterRegistry = meterRegistry;
    }

    /**
     * Record a contract-modification review event.
     *
     * ⚠ PAIR-UNIQUE DEBT: obs-metric-unbounded-cardinality.
     * The {@code user_id} label is unbounded — with 50k unique reviewers
     * (CORs + COs + DCAA auditors across all tenants) the time-series count
     * blows up. Datadog billing flags this as a cost-attack pattern.
     *
     * fixed_looks_like:
     *   meterRegistry.counter("contract_modification.reviewed",
     *       "tenant", tenant,
     *       "outcome", outcome  // bounded enum: APPROVED/REJECTED/PENDING
     *   ).increment();
     */
    public void recordReview(String userId, String tenant) {
        meterRegistry.counter("contract_modification.reviewed",
            "user_id", userId,        // ⚠ unbounded cardinality
            "tenant", tenant
        ).increment();
    }

    /** Expose the label keys actually applied to the counter for the locked debt test. */
    public List<String> labelKeysApplied(String userId, String tenant) {
        recordReview(userId, tenant);
        List<String> keys = new ArrayList<>();
        meterRegistry.find("contract_modification.reviewed").meters().forEach(m ->
            m.getId().getTags().stream().map(Tag::getKey).forEach(keys::add)
        );
        return keys;
    }

    /** Convenience accessor for test-time meter introspection. */
    public Tags currentLabelsFor(String userId, String tenant) {
        return Tags.of("user_id", userId, "tenant", tenant);
    }
}
