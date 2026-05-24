package com.karsunfde.contractflow.invoicereview.client;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.util.Map;

/**
 * ⚠ DELIBERATE BROWNFIELD DEBT — Item 3 ⚠
 *
 * Calls contract-modification-service over synchronous REST. No:
 *   - {@code @CircuitBreaker} (Resilience4j not on the classpath)
 *   - {@code @TimeLimiter}
 *   - {@code @Retry}
 *   - fallback method
 *   - timeout on the RestTemplate
 *   - idempotency key on state-mutating calls
 *
 * A slow upstream piles threads on this service's Tomcat connector. A load
 * test from invoice-review-service → contract-modification-service (artificially slow)
 * will reproduce thread exhaustion.
 *
 * Cohort fixes in W4 Thu reliability engineering.
 */
@Component
public class ContractModificationClient {

    private static final Logger log = LoggerFactory.getLogger(ContractModificationClient.class);

    private final RestTemplate restTemplate;

    @Value("${contractModification.service.url:http://contract-modification-service:8081}")
    private String contractModificationServiceUrl;

    @Autowired
    public ContractModificationClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    /**
     * Fetch a contractModification by id from the upstream service.
     *
     * ⚠ No try/catch — a 5xx from upstream propagates as a 500 from us.
     * ⚠ No timeout — a 30-second hang upstream is a 30-second hang here.
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> getContractModification(String id) {
        String url = contractModificationServiceUrl + "/api/contract-modifications/" + id;
        // Item 6 — invoice-review-service uses traceId key.
        log.info("calling contract-modification-service url={} traceId=N/A", url);
        return restTemplate.getForObject(url, Map.class);
    }
}
