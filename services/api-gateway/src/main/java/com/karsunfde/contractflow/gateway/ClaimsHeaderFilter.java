package com.karsunfde.contractflow.gateway;

import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

/**
 * Propagates the authenticated caller's identity to downstream services as
 * gateway-asserted headers (ADR-0005 §11 — tenant identity is never trusted
 * from the application layer / request body):
 *
 *   X-Tenant-Id ← JWT {@code agency_id} claim
 *   X-User-Id   ← JWT {@code sub} claim
 *
 * Any client-supplied copies of these headers are stripped unconditionally
 * (header-spoofing defense) — they are set ONLY from verified JWT claims.
 * Downstream services (e.g. ai-orchestrator /retrieve) treat them as the
 * sole source of identity, which is safe because those services are only
 * reachable on the compose-internal network through this gateway.
 *
 * Note: the /api/public/** signature-skip path (deliberate debt Item 1,
 * docs/brownfield-debt.md) does not route to ai-orchestrator; on that path
 * no JwtAuthenticationToken is established, so no identity headers are
 * injected — the strip still applies.
 */
@Component
public class ClaimsHeaderFilter implements GlobalFilter, Ordered {

    public static final String TENANT_HEADER = "X-Tenant-Id";
    public static final String USER_HEADER = "X-User-Id";

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        // Always strip inbound identity headers — clients must not be able to
        // assert their own tenant or user identity.
        ServerWebExchange stripped = exchange.mutate()
            .request(r -> r.headers(h -> {
                h.remove(TENANT_HEADER);
                h.remove(USER_HEADER);
            }))
            .build();

        return stripped.getPrincipal()
            .filter(JwtAuthenticationToken.class::isInstance)
            .cast(JwtAuthenticationToken.class)
            .map(jwtAuth -> {
                String tenantId = jwtAuth.getToken().getClaimAsString("agency_id");
                String userId = jwtAuth.getToken().getSubject();
                ServerHttpRequest mutated = stripped.getRequest().mutate()
                    .headers(h -> {
                        if (tenantId != null && !tenantId.isBlank()) {
                            h.set(TENANT_HEADER, tenantId);
                        }
                        if (userId != null && !userId.isBlank()) {
                            h.set(USER_HEADER, userId);
                        }
                    })
                    .build();
                return stripped.mutate().request(mutated).build();
            })
            .defaultIfEmpty(stripped)
            .flatMap(chain::filter);
    }

    @Override
    public int getOrder() {
        // Run after security has populated the principal but before routing.
        return Ordered.LOWEST_PRECEDENCE;
    }
}
