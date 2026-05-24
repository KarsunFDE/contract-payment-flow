package com.karsunfde.contractflow.contractmodification.controller;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * Lightweight health-probe endpoint for k8s readiness + liveness.
 *
 * Pair-unique brownfield-debt (Pair 2 / D-059):
 *   - obs-healthcheck-always-200 — {@link #health()} always returns
 *     HTTP 200 + status=UP regardless of downstream state. Mongo could
 *     be unreachable, Bedrock unreachable, the invoice-review-service
 *     could be down — k8s readiness still says "ready". Cohort fixes
 *     in W5 (AIOps day) by switching to Spring Boot Actuator's
 *     /actuator/health with HealthIndicator beans for Mongo + Bedrock +
 *     the downstream services.
 *
 * Note: a separate /actuator/health endpoint may also exist via
 * spring-boot-starter-actuator's auto-config. This dedicated /health
 * controller is what the k8s deployment manifests + GHA smoke-test
 * scripts point at — that's the production-path bug. Cohort decides
 * whether to delete this controller and route k8s at /actuator/health,
 * or fix this controller in place.
 */
@RestController
@RequestMapping("/health")
public class HealthController {

    /**
     * ⚠ PAIR-UNIQUE DEBT: obs-healthcheck-always-200.
     * Always returns 200. Does not check Mongo, Bedrock, downstream
     * services. K8s cascades failures because readiness is a lie.
     *
     * fixed_looks_like:
     *   inject a HealthIndicator chain (Mongo + Bedrock + downstream).
     *   Return 503 when any indicator is DOWN.
     */
    @GetMapping
    public Map<String, String> health() {
        return Map.of("status", "UP");
    }
}
