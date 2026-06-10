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
 *   /api/ai/**              → ai-orchestrator:8000 (StripPrefix(2))
 *   /api/public/**          → contract-modification-service (signature-skipped path — Item 1)
 *
 * The ai-orchestrator (FastAPI) mounts its routers at the service root —
 * /corpus/*, /retrieve, /eval/*, /draft-amendment, /answer-qa, /agent/* — with
 * no /api/ai prefix. StripPrefix(2) drops the two leading segments so the
 * gateway convention /api/ai/<path> maps to the orchestrator's <path>
 * (e.g. /api/ai/corpus/upload → /corpus/upload, /api/ai/retrieve → /retrieve,
 * /api/ai/eval/ssdd-draft → /eval/ssdd-draft).
 */
@Configuration
public class RouteConfig {

    @Bean
    public RouteLocator routes(RouteLocatorBuilder builder) {
        String contractModificationUrl = System.getenv().getOrDefault(
            "CONTRACT_MODIFICATION_SERVICE_URL", "http://contract-modification-service:8081");
        String invoiceReviewUrl = System.getenv().getOrDefault(
            "INVOICE_REVIEW_SERVICE_URL", "http://invoice-review-service:8082");
        String aiUrl = System.getenv().getOrDefault(
            "AI_ORCHESTRATOR_URL", "http://ai-orchestrator:8000");

        return builder.routes()
            .route("contractModifications", r -> r.path("/api/contract-modifications/**").uri(contractModificationUrl))
            .route("invoiceReviews",   r -> r.path("/api/invoice-reviews/**").uri(invoiceReviewUrl))
            .route("ai",            r -> r.path("/api/ai/**").filters(f -> f.stripPrefix(2)).uri(aiUrl))
            // Item 1 — public path forwards to contract-modification-service after signature-skip.
            .route("public",        r -> r.path("/api/public/**").uri(contractModificationUrl))
            .build();
    }
}
