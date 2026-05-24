package com.karsunfde.contractflow.invoicereview;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.web.client.RestTemplate;

/**
 * contract-payment-flow — InvoiceReview Service.
 *
 * Coordinates invoice_review panels for contract_modifications. Calls contract-modification-service
 * synchronously to fetch contract_modification data (⚠ no circuit breaker — Item 3).
 *
 * Brownfield-debt items in this service:
 *   - Item 3 — No Resilience4j circuit breaker on outbound calls
 *   - Item 6 — Logs traceId (inconsistent with X-Request-ID / correlationId)
 *   - Item 11 — Dockerfile uses :latest
 */
@SpringBootApplication
public class InvoiceReviewServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(InvoiceReviewServiceApplication.class, args);
    }

    /**
     * ⚠ DELIBERATE — Item 3: no timeout configuration, no error handler, no
     * circuit breaker wrapper. A slow contract-modification-service will pile threads
     * on this RestTemplate.
     */
    @Bean
    public RestTemplate restTemplate() {
        return new RestTemplate();
    }
}
