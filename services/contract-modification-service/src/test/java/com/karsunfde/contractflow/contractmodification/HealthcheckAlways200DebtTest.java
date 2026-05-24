package com.karsunfde.contractflow.contractmodification;

import com.karsunfde.contractflow.contractmodification.controller.HealthController;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Locked-failing test for pair-unique brownfield-debt item
 * `obs-healthcheck-always-200` (Pair 2 / cohort_1_pair_2_contract).
 *
 * The debt: {@link HealthController#health()} always returns
 * {@code status=UP} regardless of Mongo, Bedrock, or downstream service
 * health. K8s readiness probe is a lie; cascade failures are not surfaced.
 *
 * Detection: the EXPECTED-AFTER-FIX implementation is a Spring Boot
 * Actuator {@code HealthEndpoint} or a controller that delegates to
 * registered {@code HealthIndicator} beans. While debt locked, the body
 * is a hard-coded {@code Map.of("status", "UP")} — no dependency
 * resolution. We probe for that hardcoded shape.
 *
 * Lifecycle: FAILS while debt locked (controller returns the hardcoded
 * map with no dependency awareness). PASSES after W5 modernization
 * (HealthIndicator chain wired in, controller surfaces dependency
 * status).
 *
 * Test-infra note: adapted from pool sketch which proposed stopping a
 * live Mongo container. Lighter unit-style test asserts the controller
 * does NOT hardcode UP — it must consult some indicator. We probe via
 * type signature: the EXPECTED-AFTER-FIX returns a richer payload than
 * a 1-entry map.
 */
@Tag("brownfield_debt")
@Tag("brownfield_debt_pair_unique")
class HealthcheckAlways200DebtTest {

    @Test
    void healthEndpointConsultsDependencies_DEBT_LOCKED() {
        HealthController controller = new HealthController();
        Map<String, String> response = controller.health();

        // EXPECTED-AFTER-FIX: response includes per-dependency status
        // (e.g., "mongo": "UP", "bedrock": "UP", "downstreams": "DEGRADED").
        // While debt locked: response is exactly Map.of("status", "UP") —
        // a single entry, no dependency keys. Fails on size.
        assertThat(response)
            .as("health endpoint must surface per-dependency status, not a hardcoded UP")
            .containsKey("status")
            .hasSizeGreaterThan(1);
    }
}
