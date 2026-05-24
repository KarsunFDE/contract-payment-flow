package com.karsunfde.contractflow.gateway;

import org.springframework.cloud.gateway.route.RouteLocator;
import org.springframework.cloud.gateway.route.builder.RouteLocatorBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Gateway route definitions.
 *
 * Routes:
 *   /api/contract-modifications/**   → contract-modification-service:8081
 *   /api/invoice-reviews/**     → invoice-review-service:8082
 *   /api/ai/**              → ai-orchestrator:8000
 *   /api/public/**          → contract-modification-service (signature-skipped path — Item 1)
 */
@Configuration
public class RouteConfig {

    @Bean
    public RouteLocator routes(RouteLocatorBuilder builder) {
        String contract_modificationUrl = System.getenv().getOrDefault(
            "CONTRACT_MODIFICATION_SERVICE_URL", "http://contract-modification-service:8081");
        String invoice_reviewUrl = System.getenv().getOrDefault(
            "INVOICE_REVIEW_SERVICE_URL", "http://invoice-review-service:8082");
        String aiUrl = System.getenv().getOrDefault(
            "AI_ORCHESTRATOR_URL", "http://ai-orchestrator:8000");

        return builder.routes()
            .route("contract_modifications", r -> r.path("/api/contract-modifications/**").uri(contract_modificationUrl))
            .route("invoice_reviews",   r -> r.path("/api/invoice-reviews/**").uri(invoice_reviewUrl))
            .route("ai",            r -> r.path("/api/ai/**").uri(aiUrl))
            // Item 1 — public path forwards to contract-modification-service after signature-skip.
            .route("public",        r -> r.path("/api/public/**").uri(contract_modificationUrl))
            .build();
    }
}
